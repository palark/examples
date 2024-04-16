import json
import os
import random
from datetime import datetime, timezone
import boto3
from botocore.exceptions import ClientError

size_order_str = os.environ.get("SIZE_ORDER", "[]")
SIZE_ORDER = json.loads(size_order_str)
MODIFYING_STATUSES = ["modifying", "storage-optimization", "creating"]

rds_client = boto3.client('rds')
sns_client = boto3.client('sns')
sns_topic_arn = os.environ.get('ALARMS_SNS')

def lambda_handler(event, _):
    """
    lambda function triggered by rds event
    """
    print("Received event:", event)
    # Process JSON
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

    # Get the cluster and instance info
    instance_info = rds_client.describe_db_instances(DBInstanceIdentifier=instance_identifier)
    if 'DBClusterIdentifier' not in instance_info['DBInstances'][0]:
        print(f"Instance {instance_identifier} is not a part of the cluster.")
        return

    cluster_identifier = instance_info['DBInstances'][0]['DBClusterIdentifier']
    cluster_info = rds_client.describe_db_clusters(DBClusterIdentifier=cluster_identifier)
    cluster_members = cluster_info['DBClusters'][0]['DBClusterMembers']

    # If modifying?
    if any_member_modifying(rds_client, cluster_members):
        print("An instance in the cluster is currently being modified.")
        return

    # Get the cluster status
    if is_cluster_modifying(rds_client, cluster_identifier):
        print("The cluster is currently in the modifying state.")
        return

    # Search for the 'modifying' tag
    handle_modifying_tag(rds_client, cluster_members)
    # Search for largest instance type in the cluster
    largest_instance_type = find_largest_instance_type(rds_client, cluster_members)
    print(f"The largest instance type in the cluster is {largest_instance_type}.")

    writer_instance = find_writer_instance(rds_client, cluster_members)
    eligible_readers = find_eligible_readers_for_scale_up(rds_client, cluster_members, largest_instance_type)

    # Check and scale the writer
    if writer_instance and writer_instance['DBInstanceClass'] != largest_instance_type:
        message = f"Scaling up the writer instance: {writer_instance['DBInstanceIdentifier']}"
        print(message)
        send_sns_alert(message)
        scale_instance(rds_client, writer_instance['DBInstanceIdentifier'], largest_instance_type)
        add_modifying_tag(rds_client, writer_instance['DBInstanceIdentifier'])
        return

    # Check and scale the readers
    if eligible_readers:
        instance_to_scale_up = select_random_instance(eligible_readers)
        message = f"Scaling up the reader instance: {instance_to_scale_up['DBInstanceIdentifier']}"
        print(message)
        send_sns_alert(message)
        scale_instance(rds_client, instance_to_scale_up['DBInstanceIdentifier'], largest_instance_type)
        add_modifying_tag(rds_client, instance_to_scale_up['DBInstanceIdentifier'])
        return
    print("No scaling actions required at this time.")
    send_sns_alert("The process of modifying instances in the cluster using a Lambda function has been completed.")


def any_member_modifying(client, cluster_members):
    """
    checking if any cluster instance is being modified already
    """
    for member in cluster_members:
        instance_info = client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
        if instance_info['DBInstances'][0]['DBInstanceStatus'] in MODIFYING_STATUSES:
            return True
    return False

def find_instances_of_type(client, cluster_members, instance_type):
    """
    find the instances
    """
    instances_of_type = []
    for member in cluster_members:
        instance_info = client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
        if instance_info['DBInstances'][0]['DBInstanceClass'] == instance_type:
            instances_of_type.append(instance_info['DBInstances'][0])
    return instances_of_type

def is_cluster_modifying(client, cluster_identifier):
    """
    checking if the cluster is being modified already
    """
    cluster_info = client.describe_db_clusters(DBClusterIdentifier=cluster_identifier)
    cluster_status = cluster_info['DBClusters'][0]['Status']
    modifying_statuses = ["modifying", "failing-over", "storage-optimization"]
    return cluster_status.lower() in modifying_statuses

def scale_instance(client, instance_identifier, new_instance_type):
    """
    scale the instance
    """
    try:
        if new_instance_type is None:
            # If the next instance type is not found, remove the 'modifying' tag and do not proceed with scaling
            print(f"No suitable next instance type found for {instance_identifier}. Removing the 'modifying' tag.")
            remove_tag_from_instance(rds_client, instance_identifier, 'modifying')
            return False  # Scaling was not performed

        # Continue performing the scaling if a new instance type is available
        response = client.modify_db_instance(
            DBInstanceIdentifier=instance_identifier,
            DBInstanceClass=new_instance_type,
            ApplyImmediately=True
        )
        print(f"Instance scaling response: {response}")
        return True  # Scaling was successfully initiated
    except ClientError as e:
        error_message = f"Error during the instance scaling: {e}"
        print(error_message)
        send_sns_alert(error_message)
        # In case of a scaling error, also remove the 'modifying' tag
        remove_tag_from_instance(client, instance_identifier, 'modifying')
        return False  # Scaling was not performed


def find_largest_instance_type(client, cluster_members):
    """
    find the largest instance type (its size will be used for each instance in cluster)
    """
    largest_instance_type = None

    for member in cluster_members:
        instance_info = client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
        instance_type = instance_info['DBInstances'][0]['DBInstanceClass']

        if largest_instance_type is None or instance_type_sorter(instance_type) > instance_type_sorter(largest_instance_type):
            largest_instance_type = instance_type

    return largest_instance_type

def find_writer_instance(client, cluster_members):
    """
    find the writer instance type
    """
    for member in cluster_members:
        if member['IsClusterWriter']:
            instance_info = client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
            return instance_info['DBInstances'][0]
    return None

def find_eligible_readers_for_scale_up(client, cluster_members, largest_instance_type):
    """
    find the eligible readers for scaling up
    """
    smallest_instance_type = None
    eligible_readers = []

    # Search for the smallest reader
    for member in cluster_members:
        if not member['IsClusterWriter']:
            instance_info = client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
            instance_type = instance_info['DBInstances'][0]['DBInstanceClass']
            if smallest_instance_type is None or instance_type_sorter(instance_type) < instance_type_sorter(smallest_instance_type):
                smallest_instance_type = instance_type

	# Choose the eligible readers
    if smallest_instance_type and smallest_instance_type != largest_instance_type:
        for member in cluster_members:
            if not member['IsClusterWriter']:
                instance_info = rds_client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
                if instance_info['DBInstances'][0]['DBInstanceClass'] == smallest_instance_type:
                    eligible_readers.append(instance_info['DBInstances'][0])
    return eligible_readers

def select_random_instance(eligible_readers):
    """
    select a random instance from eligible
    """
    return random.choice(eligible_readers)

def instance_type_sorter(instance_type):
    """
    sorter
    """
    return SIZE_ORDER.index(instance_type) if instance_type in SIZE_ORDER else -1

def add_modifying_tag(client, instance_identifier):
    """
    add the modifying tag and timestamp to prevent simultaneous actions at the same time
    """
    instance_arn = get_instance_arn(client, instance_identifier)
    if not instance_arn:
        print(f"ARN not found for the instance {instance_identifier}")
        return
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        client.add_tags_to_resource(
            ResourceName=instance_arn,
            Tags=[{'Key': 'modifying', 'Value': 'true'},
                  {'Key': 'modificationTimestamp', 'Value': timestamp}
                  ]
        )
        print(f"Added the 'modifying' tag to instance {instance_identifier}")
    except ClientError as e:
        error_messsage = f"Error adding the 'modifying' tag to {instance_identifier}: {e}"
        print(error_messsage)
        send_sns_alert(error_messsage)

def get_instance_arn(client, instance_identifier):
    """
    get the instance arn
    """
    instance_info = client.describe_db_instances(DBInstanceIdentifier=instance_identifier)
    return instance_info['DBInstances'][0]['DBInstanceArn']

def handle_modifying_tag(client, cluster_members):
    """
    handle the modifying tag
    """
    modifying_instances = find_instances_with_tag(client, cluster_members, 'modifying')
    for inst in modifying_instances:
        print(f"Instance {inst['DBInstanceIdentifier']} has the 'modifying' tag.")
        remove_tag_from_instance(client, inst['DBInstanceIdentifier'], 'modifying')

def find_instances_with_tag(client, cluster_members, tag_key):
    """
    find the modifying tag
    """
    instances_with_tag = []
    for member in cluster_members:
        instance_info = client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
        instance_arn = instance_info['DBInstances'][0]['DBInstanceArn']
        tags = client.list_tags_for_resource(ResourceName=instance_arn)
        if any(t['Key'] == tag_key for t in tags['TagList']):
            instances_with_tag.append(instance_info['DBInstances'][0])
    return instances_with_tag

def remove_tag_from_instance(client, instance_identifier, tag_key):
    """
    remove the modifying tag
    """
    instance_arn = get_instance_arn(client, instance_identifier)
    rds_client.remove_tags_from_resource(ResourceName=instance_arn, TagKeys=[tag_key])

def send_sns_alert(message):
    """
    SNS alerting
    """
    try:
        sns_client.publish(
            TopicArn=sns_topic_arn,
            Message=message
        )
        print(f"SNS alert sent. Message: {message}")
    except ClientError as e:
        print(f"Failed to send an SNS alert. Error: {e}")
