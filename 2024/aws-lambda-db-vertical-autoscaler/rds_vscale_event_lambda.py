import boto3
import json
import random
import re
import os

SIZE_ORDER = ['small', 'medium', 'large', 'xlarge', '2xlarge', '4xlarge', '8xlarge', '12xlarge', '16xlarge', '24xlarge']

def lambda_handler(event, context):
    print("Received event:", event)
    rds_client = boto3.client('rds')
    # work with JSON
    sns_message = json.loads(event['Records'][0]['Sns']['Message'])
    print("SNS message:", sns_message) 
    cluster_name = sns_message.get('Tags', {}).get('Cluster', None)
    print("Cluster name:", cluster_name)
    expected_cluster_name = os.environ['CLUSTER_NAME']
    if cluster_name != expected_cluster_name:
        print(f"Ignoring event for cluster: {cluster_name}")
        return
    
    if sns_message['Event ID'] != 'http://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_Events.Messages.html#RDS-EVENT-0014':
        print(f"Ignoring event with ID: {sns_message['Event ID']}")
        return
    
    if 'Source ID' not in sns_message:
        print("Source ID not found in SNS message")
        return

    instance_identifier = sns_message['Source ID']

    # Get cluster and instance info
    instance_info = rds_client.describe_db_instances(DBInstanceIdentifier=instance_identifier)
    if 'DBClusterIdentifier' not in instance_info['DBInstances'][0]:
        print(f"Instance {instance_identifier} is not part of a cluster.")
        return

    cluster_identifier = instance_info['DBInstances'][0]['DBClusterIdentifier']
    cluster_info = rds_client.describe_db_clusters(DBClusterIdentifier=cluster_identifier)
    cluster_members = cluster_info['DBClusters'][0]['DBClusterMembers']

    # If modifying?
    if any_member_modifying(rds_client, cluster_members):
        print("An instance in the cluster is currently modifying.")
        return

    # Get cluster status
    if is_cluster_modifying(rds_client, cluster_identifier):
        print("The cluster is currently in a modifying state.")
        return

    # Searching for tag 'modifying'
    handle_modifying_tag(rds_client, cluster_members)
    # Searching for largest instance type in cluster
    largest_instance_type, engine_version = find_largest_instance_type(rds_client, cluster_members)
    print(f"The largest instance type in the cluster is {largest_instance_type} with engine version {engine_version}.")

    writer_instance = find_writer_instance(rds_client, cluster_members)
    eligible_readers = find_eligible_readers_for_scale_up(rds_client, cluster_members, largest_instance_type)

    # Checking and increasing writer
    if writer_instance and writer_instance['DBInstanceClass'] != largest_instance_type:
        print(f"Scaling up writer instance: {writer_instance['DBInstanceIdentifier']}")
        scale_instance(rds_client, writer_instance['DBInstanceIdentifier'], largest_instance_type)
        add_modifying_tag(rds_client, writer_instance['DBInstanceIdentifier'])
        return  

    # checking and increasing readers
    if eligible_readers:
        instance_to_scale_up = select_random_instance(eligible_readers)
        print(f"Scaling up reader instance: {instance_to_scale_up['DBInstanceIdentifier']}")
        scale_instance(rds_client, instance_to_scale_up['DBInstanceIdentifier'], largest_instance_type)
        add_modifying_tag(rds_client, instance_to_scale_up['DBInstanceIdentifier'])
        return
    print("No scaling actions required at this time.")

def any_member_modifying(rds_client, cluster_members):
    for member in cluster_members:
        instance_info = rds_client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
        if instance_info['DBInstances'][0]['DBInstanceStatus'] in ["modifying", "storage-optimization", "creating", "rebooting"]:
            return True
    return False

def find_instances_of_type(rds_client, cluster_members, instance_type):
    instances_of_type = []
    for member in cluster_members:
        instance_info = rds_client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
        if instance_info['DBInstances'][0]['DBInstanceClass'] == instance_type:
            instances_of_type.append(instance_info['DBInstances'][0])
    return instances_of_type

def is_cluster_modifying(rds_client, cluster_identifier):
    cluster_info = rds_client.describe_db_clusters(DBClusterIdentifier=cluster_identifier)
    cluster_status = cluster_info['DBClusters'][0]['Status']
    modifying_statuses = ["modifying", "failing-over", "storage-optimization"]
    return cluster_status.lower() in modifying_statuses

def scale_instance(rds_client, instance_identifier, new_instance_type):
    try:
        response = rds_client.modify_db_instance(
            DBInstanceIdentifier=instance_identifier,
            DBInstanceClass=new_instance_type,
            ApplyImmediately=True
        )
        print(f"Instance scaling response: {response}")
    except Exception as e:
        print(f"Error during instance scaling: {e}")

def find_largest_instance_type(rds_client, cluster_members):
    largest_instance_type = None
    engine_version = None

    for member in cluster_members:
        instance_info = rds_client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
        instance_type = instance_info['DBInstances'][0]['DBInstanceClass']
        current_engine_version = instance_info['DBInstances'][0]['EngineVersion']

        if largest_instance_type is None or instance_type_sorter(instance_type) > instance_type_sorter(largest_instance_type):
            largest_instance_type = instance_type
            engine_version = current_engine_version

    return largest_instance_type, engine_version

def find_writer_instance(rds_client, cluster_members):
    for member in cluster_members:
        if member['IsClusterWriter']:
            instance_info = rds_client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
            return instance_info['DBInstances'][0]  
    return None

def find_eligible_readers_for_scale_up(rds_client, cluster_members, largest_instance_type):
    smallest_instance_type = None
    eligible_readers = []

    # Search of the smallest reader
    for member in cluster_members:
        if not member['IsClusterWriter']:
            instance_info = rds_client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
            instance_type = instance_info['DBInstances'][0]['DBInstanceClass']
            if smallest_instance_type is None or instance_type_sorter(instance_type) < instance_type_sorter(smallest_instance_type):
                smallest_instance_type = instance_type

# Choose eligible readers
    if smallest_instance_type and smallest_instance_type != largest_instance_type:
        for member in cluster_members:
            if not member['IsClusterWriter']:
                instance_info = rds_client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
                if instance_info['DBInstances'][0]['DBInstanceClass'] == smallest_instance_type:
                    eligible_readers.append(instance_info['DBInstances'][0])
    return eligible_readers

def select_random_instance(eligible_readers):
    return random.choice(eligible_readers)

def instance_type_sorter(instance_type):
    match = re.search(r"db\.([a-zA-Z0-9]+)\.(\w+)", instance_type)
    if match:
        _, size = match.groups()
        return SIZE_ORDER.index(size) if size in SIZE_ORDER else -1
    return -1

def get_next_instance_type(current_type):
    current_size_match = re.search(r"db\.[a-zA-Z0-9]+\.(\w+)", current_type)
    if current_size_match:
        current_size = current_size_match.group(1)
        if current_size in SIZE_ORDER:
            current_index = SIZE_ORDER.index(current_size)
            if current_index + 1 < len(SIZE_ORDER):
                return current_type.replace(current_size, SIZE_ORDER[current_index + 1])
    return current_type

def add_modifying_tag(rds_client, instance_identifier):
    try:
        instance_arn = get_instance_arn(rds_client, instance_identifier)
        print(f"Adding 'modifying' tag to instance {instance_identifier}, ARN: {instance_arn}")

        rds_client.add_tags_to_resource(
            ResourceName=instance_arn,
            Tags=[{'Key': 'modifying', 'Value': 'true'}]
        )
        print(f"'modifying' tag added to instance {instance_identifier}")
    except Exception as e:
        print(f"Error while adding 'modifying' tag to instance {instance_identifier}: {e}")

def get_instance_arn(rds_client, instance_identifier):
    instance_info = rds_client.describe_db_instances(DBInstanceIdentifier=instance_identifier)
    return instance_info['DBInstances'][0]['DBInstanceArn']

def handle_modifying_tag(rds_client, cluster_members):
    modifying_instances = find_instances_with_tag(rds_client, cluster_members, 'modifying')
    for inst in modifying_instances:
        print(f"Instance {inst['DBInstanceIdentifier']} has 'modifying' tag.")
        remove_tag_from_instance(rds_client, inst['DBInstanceIdentifier'], 'modifying')

def find_instances_with_tag(rds_client, cluster_members, tag_key):
    instances_with_tag = []
    for member in cluster_members:
        instance_info = rds_client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
        instance_arn = instance_info['DBInstances'][0]['DBInstanceArn']
        tags = rds_client.list_tags_for_resource(ResourceName=instance_arn)
        if any(t['Key'] == tag_key for t in tags['TagList']):
            instances_with_tag.append(instance_info['DBInstances'][0])
    return instances_with_tag

def remove_tag_from_instance(rds_client, instance_identifier, tag_key):
    instance_arn = get_instance_arn(rds_client, instance_identifier)
    rds_client.remove_tags_from_resource(ResourceName=instance_arn, TagKeys=[tag_key])
