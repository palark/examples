import boto3
import json
import re
import random

SIZE_ORDER = ['small', 'medium', 'large', 'xlarge', '2xlarge', '4xlarge', '8xlarge', '12xlarge', '16xlarge', '24xlarge']

def get_instance_details(instance_identifier):
    rds_client = boto3.client('rds')
    try:
        response = rds_client.describe_db_instances(DBInstanceIdentifier=instance_identifier)
        instance_info = response['DBInstances'][0]
        instance_class = instance_info['DBInstanceClass']
        cluster_identifier = instance_info.get('DBClusterIdentifier', None)
        return instance_class, cluster_identifier
    except Exception as e:
        print(f"Error getting DB instance details: {e}")
        return None, None

def get_cluster_version(cluster_identifier):
    rds_client = boto3.client('rds')
    try:
        response = rds_client.describe_db_clusters(DBClusterIdentifier=cluster_identifier)
        cluster_info = response['DBClusters'][0]
        return cluster_info['EngineVersion']
    except Exception as e:
        print(f"Error getting DB cluster version: {e}")
        return None

def get_instance_family(instance_type):
    parts = instance_type.split('.')
    return parts[1] if len(parts) > 1 else None

def get_orderable_instance_types(engine, engine_version, current_family):
    rds_client = boto3.client('rds')
    response = rds_client.describe_orderable_db_instance_options(
        Engine=engine,
        EngineVersion=engine_version
    )
    return [opt['DBInstanceClass'] for opt in response['OrderableDBInstanceOptions']
            if opt['DBInstanceClass'].startswith("db." + current_family + ".")]

def instance_type_sorter(instance_type):
    match = re.search(r"db\.([a-zA-Z0-9]+)\.(\w+)", instance_type)
    if match:
        _, size = match.groups()
        return SIZE_ORDER.index(size) if size in SIZE_ORDER else -1
    return -1

def get_next_instance_type(current_type, available_types):
    current_size_match = re.search(r"db\.[a-zA-Z0-9]+\.(\w+)", current_type)
    if current_size_match:
        current_size = current_size_match.group(1)
        if current_size in SIZE_ORDER:
            current_index = SIZE_ORDER.index(current_size)
            for type in available_types:
                size_match = re.search(r"db\.[a-zA-Z0-9]+\.(\w+)", type)
                if size_match and SIZE_ORDER.index(size_match.group(1)) > current_index:
                    return type
    return current_type

def change_instance_type(instance_identifier, new_instance_type):
    rds_client = boto3.client('rds')
    try:
        response = rds_client.modify_db_instance(
            DBInstanceIdentifier=instance_identifier,
            DBInstanceClass=new_instance_type,
            ApplyImmediately=True
        )
        return response, None
    except Exception as e:
        print(f"Error modifying DB instance: {e}")
        return None, str(e)

def get_instance_arn(rds_client, instance_identifier):
    try:
        instance_info = rds_client.describe_db_instances(DBInstanceIdentifier=instance_identifier)
        return instance_info['DBInstances'][0]['DBInstanceArn']
    except Exception as e:
        print(f"Error getting instance ARN for {instance_identifier}: {e}")
        return None

def add_modifying_tag(rds_client, instance_identifier):
    instance_arn = get_instance_arn(rds_client, instance_identifier)
    if not instance_arn:
        print(f"ARN not found for instance {instance_identifier}")
        return

    try:
        rds_client.add_tags_to_resource(
            ResourceName=instance_arn,
            Tags=[{'Key': 'modifying', 'Value': 'true'}]
        )
        print(f"Added 'modifying' tag to instance {instance_identifier}")
    except Exception as e:
        print(f"Error adding 'modifying' tag to {instance_identifier}: {e}")

def any_instance_has_modifying_tag(rds_client, cluster_instances):
    for member in cluster_instances:
        instance_arn = get_instance_arn(rds_client, member['DBInstanceIdentifier'])
        tags = rds_client.list_tags_for_resource(ResourceName=instance_arn)['TagList']
        if any(tag['Key'] == 'modifying' for tag in tags):
            return True
    return False

def is_instance_modifying(rds_client, instance_identifier):
    try:
        instance_info = rds_client.describe_db_instances(DBInstanceIdentifier=instance_identifier)['DBInstances'][0]
        return instance_info['DBInstanceStatus'] in ["modifying", "configuring-enhanced-monitoring", "storage-optimization"]
    except Exception as e:
        print(f"Error checking if instance is modifying: {e}")
        return False


def lambda_handler(event, context):
    try:
        print("Received event: " + json.dumps(event, indent=2))
        rds_client = boto3.client('rds')

        for record in event['Records']:
            sns_message = json.loads(record['Sns']['Message'])
            db_instance_identifier = None
            for dimension in sns_message['Trigger']['Dimensions']:
                if dimension['name'] == 'DBInstanceIdentifier':
                    db_instance_identifier = dimension['value']
                    break

            if db_instance_identifier is None:
                raise ValueError("DBInstanceIdentifier not found in CloudWatch Alarm event")

            instance_type, cluster_identifier = get_instance_details(db_instance_identifier)
            if not cluster_identifier:
                raise ValueError("Instance is not part of any RDS cluster")

            if is_instance_modifying(rds_client, db_instance_identifier):
                print(f"Instance {db_instance_identifier} is currently modifying.")
                continue

            cluster_version = get_cluster_version(cluster_identifier)
            current_family = get_instance_family(instance_type)
            available_types = get_orderable_instance_types('aurora-postgresql', cluster_version, current_family)
            available_types.sort(key=instance_type_sorter)

            cluster_response = rds_client.describe_db_clusters(DBClusterIdentifier=cluster_identifier)
            cluster_instances = cluster_response['DBClusters'][0]['DBClusterMembers']

            writer_instance_identifier = None
            writer_instance_type = None  # Define the variable outside the loop
            is_writer_smallest = True

            for member in cluster_instances:
                member_instance_type, _ = get_instance_details(member['DBInstanceIdentifier'])
                if member['IsClusterWriter']:
                    writer_instance_identifier = member['DBInstanceIdentifier']
                    writer_instance_type = member_instance_type

            # Ensure writer_instance_type is defined before comparing
            if writer_instance_type is None:
                raise ValueError("Writer instance type not found in the cluster")


            for member in cluster_instances:
                if not member['IsClusterWriter']:
                    member_instance_type, _ = get_instance_details(member['DBInstanceIdentifier'])
                    if instance_type_sorter(member_instance_type) <= instance_type_sorter(writer_instance_type):
                        is_writer_smallest = False

            # Check if any instance is modifying or has modifying tag
            if any_instance_has_modifying_tag(rds_client, cluster_instances):
                print("An instance in the cluster has 'modifying' tag.")
                continue
            
            if is_writer_smallest:
                # Scaling up writer
                new_writer_instance_type = get_next_instance_type(writer_instance_type, available_types)
                if new_writer_instance_type != writer_instance_type:
                    change_response, error = change_instance_type(writer_instance_identifier, new_writer_instance_type)
                    if not error:
                        print(f"Changed writer instance type to {new_writer_instance_type}")
                        add_modifying_tag(rds_client, writer_instance_identifier)
                    else:
                        print(f"Failed to change writer instance type. Error: {error}")
                        return {"errorMessage": f"Failed to change writer instance type. Error: {error}"}
                else:
                    print(f"All instances is already at the maximum type in its family.")
                continue

            # Process reader instances
            eligible_readers = []
            smallest_size = None
            for member in cluster_instances:
                if not member['IsClusterWriter']:
                    member_instance_type, _ = get_instance_details(member['DBInstanceIdentifier'])
                    if member_instance_type != available_types[-1]:  # Exclude if at maximum size
                        if smallest_size is None or instance_type_sorter(member_instance_type) <= instance_type_sorter(smallest_size):
                            if smallest_size is None or instance_type_sorter(member_instance_type) < instance_type_sorter(smallest_size):
                                eligible_readers = []
                                smallest_size = member_instance_type
                            eligible_readers.append(member['DBInstanceIdentifier'])

            if eligible_readers:
                # Choose random from smallest 
                reader_to_scale = random.choice(eligible_readers)
                new_reader_instance_type = get_next_instance_type(smallest_size, available_types)
                if new_reader_instance_type != smallest_size:
                    change_response, error = change_instance_type(reader_to_scale, new_reader_instance_type)
                    if not error:
                        print(f"Changed reader instance type to {new_reader_instance_type}")
                        add_modifying_tag(rds_client, reader_to_scale)
                    else:
                        print(f"Failed to change reader instance type. Error: {error}")
                        return {"errorMessage": f"Failed to change reader instance type. Error: {error}"}
                else:
                    print(f"Reader instance is already at the maximum type in its family.")
            else:
                print("No eligible readers to scale up.")

        return {
            'statusCode': 200,
            'body': json.dumps("Processed instances in cluster.")
        }
    except Exception as e:
        print(f"Failed to execute the function. Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f"Failed to execute the function. Error: {str(e)}")
        }
