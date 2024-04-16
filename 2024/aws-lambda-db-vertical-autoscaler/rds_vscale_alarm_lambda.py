import json
import os
import random
import re
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError
import boto3


size_order_str = os.environ.get("SIZE_ORDER", "[]")
SIZE_ORDER = json.loads(size_order_str)
MODIFY_COOLDOWN_PERIOD = int(os.environ.get("MODIFY_COOLDOWN_PERIOD", "900"))
MODIFYING_STATUSES = ["modifying", "storage-optimization", "creating", "rebooting"]

rds_client = boto3.client('rds')
sns_client = boto3.client('sns')
sns_topic_arn = os.environ.get('ALARMS_SNS')

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
        print(f"Failed to send SNS alert. Error: {e}")

def get_instance_details(client, instance_identifier):
    """
    get instance details
    """
    try:
        response = client.describe_db_instances(DBInstanceIdentifier=instance_identifier)
        instance_info = response['DBInstances'][0]
        instance_class = instance_info['DBInstanceClass']
        cluster_identifier = instance_info.get('DBClusterIdentifier', None)
        return instance_class, cluster_identifier
    except ClientError as e:
        error_message = f"Error getting DB instance details: {e}"
        print(error_message)
        send_sns_alert(error_message)
        return None, None

def get_cluster_version(client, cluster_identifier):
    """
    get cluster version
    """
    try:
        response = client.describe_db_clusters(DBClusterIdentifier=cluster_identifier)
        cluster_info = response['DBClusters'][0]
        return cluster_info['EngineVersion']
    except ClientError as e:
        error_message = f"Error getting DB cluster version: {e}"
        print(error_message)
        send_sns_alert(error_message)
        return None



def instance_type_sorter(instance_type):
    """
    instance type sorter
    """
    return SIZE_ORDER.index(instance_type) if instance_type in SIZE_ORDER else -1


def change_instance_type(client, instance_identifier, new_instance_type):
    """
    change instance type
    """
    try:
        response = client.modify_db_instance(
            DBInstanceIdentifier=instance_identifier,
            DBInstanceClass=new_instance_type,
            ApplyImmediately=True
        )
        return response, None
    except ClientError as e:
        error_message = f"An error during the attempt to vertically scale the RDS instance {e}"
        print(error_message)
        send_sns_alert(error_message)
        return None, str(e)

def get_instance_arn(client, instance_identifier):
    """
    get instance arn
    """
    try:
        instance_info = client.describe_db_instances(DBInstanceIdentifier=instance_identifier)
        return instance_info['DBInstances'][0]['DBInstanceArn']
    except ClientError as e:
        error_message = f"Error getting instance ARN for {instance_identifier}: {e}"
        print(error_message)
        send_sns_alert(error_message)
        return None


def add_modifying_tag(client, instance_identifier):
    """
    add modifying tag and timestamp to prevent a few actions in one period
    """
    instance_arn = get_instance_arn(client, instance_identifier)
    if not instance_arn:
        print(f"ARN not found for instance {instance_identifier}")
        return
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        client.add_tags_to_resource(
            ResourceName=instance_arn,
            Tags=[{'Key': 'modifying', 'Value': 'true'},
                  {'Key': 'modificationTimestamp', 'Value': timestamp}
                  ]
        )
        print(f"Added 'modifying' tag to instance {instance_identifier}")
    except ClientError as e:
        error_message = f"Error adding 'modifying' tag to {instance_identifier}: {e}"
        print(error_message)
        send_sns_alert(error_message)

def any_instance_has_modifying_tag(client, cluster_instances):
    """
    search if modifying tag exists
    """
    for member in cluster_instances:
        instance_arn = get_instance_arn(client, member['DBInstanceIdentifier'])
        tags = rds_client.list_tags_for_resource(ResourceName=instance_arn)['TagList']
        if any(tag['Key'] == 'modifying' for tag in tags):
            return True
    return False


def modification_timestamps(client, cluster_instances, cooldown_period):
    """
    modification timestamps workflow
    """
    now = datetime.now(timezone.utc)
    expired_instances = []
    cooldown_not_expired = False

    for member in cluster_instances:
        instance_identifier = member['DBInstanceIdentifier']
        instance_arn = get_instance_arn(client, instance_identifier)
        tags = client.list_tags_for_resource(ResourceName=instance_arn)['TagList']

        for tag in tags:
            if tag['Key'] == 'modificationTimestamp':
                tag_timestamp = datetime.fromisoformat(tag['Value'])
                time_diff_seconds = (now - tag_timestamp).total_seconds()
                cooldown_seconds = timedelta(seconds=cooldown_period).total_seconds()

                if time_diff_seconds >= cooldown_seconds:
                    expired_instances.append(instance_identifier)
                else:
                    cooldown_not_expired = True

    for instance_identifier in expired_instances:
        instance_arn = get_instance_arn(rds_client, instance_identifier)
        rds_client.remove_tags_from_resource(
            ResourceName=instance_arn,
            TagKeys=['modificationTimestamp']
        )

    return cooldown_not_expired


def any_member_modifying(client, cluster_instances):
    """
    checking if any cluster instance already modifing
    """
    for member in cluster_instances:
        instance_info = client.describe_db_instances(DBInstanceIdentifier=member['DBInstanceIdentifier'])
        if instance_info['DBInstances'][0]['DBInstanceStatus'] in MODIFYING_STATUSES:
            return True
    return False


def lambda_handler(event, _):
    """
    lambda function triggered by alarm
    """
    print("Received event: " + json.dumps(event, indent=2))
    try:
        for record in event['Records']:
            sns_message = json.loads(record['Sns']['Message'])
            db_instance_identifier = None
            for dimension in sns_message['Trigger']['Dimensions']:
                if dimension['name'] == 'DBInstanceIdentifier':
                    db_instance_identifier = dimension['value']
                    break

            if db_instance_identifier is None:
                raise ValueError("DBInstanceIdentifier not found in CloudWatch Alarm event")

            _, cluster_identifier = get_instance_details(rds_client, db_instance_identifier)
            if not cluster_identifier:
                raise ValueError("Instance is not part of any RDS cluster")

            cluster_response = rds_client.describe_db_clusters(DBClusterIdentifier=cluster_identifier)
            cluster_instances = cluster_response['DBClusters'][0]['DBClusterMembers']

            if any_member_modifying(rds_client, cluster_instances):
                print("At least one instance in the cluster is currently modifying.")
                return

            writer_instance_identifier, writer_instance_type = None, None
            for member in cluster_instances:
                if member['IsClusterWriter']:
                    writer_instance_identifier = member['DBInstanceIdentifier']
                    writer_instance_type, _ = get_instance_details(rds_client, writer_instance_identifier)

            if writer_instance_type:
                writer_size_index = SIZE_ORDER.index(writer_instance_type)

                is_writer_smallest = True
                for member in cluster_instances:
                    member_instance_type, _ = get_instance_details(rds_client, member['DBInstanceIdentifier'])
                    if member['DBInstanceIdentifier'] == writer_instance_identifier:
                        continue
                    member_size_index = SIZE_ORDER.index(member_instance_type)

                    if member_size_index < writer_size_index:
                        is_writer_smallest = False
                        break

            # Ensure writer_instance_type is defined before comparing
            if writer_instance_type is None:
                raise ValueError("Writer instance type not found in the cluster")


            for member in cluster_instances:
                if not member['IsClusterWriter']:
                    member_instance_type, _ = get_instance_details(rds_client, member['DBInstanceIdentifier'])
                    if instance_type_sorter(member_instance_type) <= instance_type_sorter(writer_instance_type):
                        is_writer_smallest = False

            # Check if any instance is modifying or has modifying tag
            if any_instance_has_modifying_tag(rds_client, cluster_instances):
                print("An instance in the cluster has 'modifying' tag.")
                return

            cooldown_not_expired = modification_timestamps(rds_client, cluster_instances, MODIFY_COOLDOWN_PERIOD)
            if cooldown_not_expired:
                message = "An attempt was made to vertically scale the RDS instance in cluster, but Cooldown period has not expired for at least one instance in the cluster."
                print(message)
                print(send_sns_alert)
                return

            if is_writer_smallest:
                # Scaling up writer
                new_writer_instance_type = SIZE_ORDER[writer_size_index + 1]
                print(f"Selected new instance type for writer: {new_writer_instance_type}")
                if new_writer_instance_type != writer_instance_type:
                    print(f"Attempting to change instance type for {writer_instance_identifier} to {new_writer_instance_type}")
                    _, error = change_instance_type(rds_client, writer_instance_identifier, new_writer_instance_type)
                    if not error:
                        message = f"Changed writer instance type to {new_writer_instance_type}"
                        print(message)
                        send_sns_alert(message)
                        add_modifying_tag(rds_client, writer_instance_identifier)
                    else:
                        error_message = f"Failed to change writer instance type. Error: {error}"
                        print(error_message)
                        send_sns_alert(error_message)
                else:
                    error_message = "Writer instance is already at the maximum size, scaling is not possible"
                    print(error_message)
                    send_sns_alert(error_message)
                continue

            # Process reader instances
            smallest_size = None
            min_size_index = float('inf')
            eligible_readers = []
            for member in cluster_instances:
                if not member['IsClusterWriter']:
                    member_instance_type, _ = get_instance_details(rds_client, member['DBInstanceIdentifier'])
                    member_index = SIZE_ORDER.index(member_instance_type)
                    if member_index < min_size_index:
                        min_size_index = member_index
                        eligible_readers = [member['DBInstanceIdentifier']]
                    elif member_index == min_size_index:
                        eligible_readers.append(member['DBInstanceIdentifier'])


            if eligible_readers and min_size_index < len(SIZE_ORDER) - 1:
                reader_to_scale = random.choice(eligible_readers)
                new_reader_instance_type = SIZE_ORDER[min_size_index + 1]
                if new_reader_instance_type != smallest_size:
                    print(f"Attempting to change instance type for {reader_to_scale} to {new_reader_instance_type}")
                    _, error = change_instance_type(rds_client, reader_to_scale, new_reader_instance_type)
                    if not error:
                        message = f"Changed reader instance type to {new_reader_instance_type}"
                        print(message)
                        send_sns_alert(message)
                        add_modifying_tag(rds_client, reader_to_scale)
                    else:
                        error_message = f"Failed to change reader instance type. Error: {error}"
                        print(error_message)
                        send_sns_alert(error_message)
                else:
                    error_message = "Reader instance is already at the maximum size, scaling is not possible"
                    print(error_message)
                    send_sns_alert(error_message)
            else:
                print("No eligible readers to scale up.")
                send_sns_alert("An attempt was made to vertically scale the RDS instance, but the conditions were not suitable.")

        return {
            'statusCode': 200,
            'body': json.dumps("Processed instances in cluster.")
        }
    except ClientError as e:
        error_message = f"Failed to execute the function. Error: {str(e)}"
        print(error_message)
        send_sns_alert(error_message)
        return {
            'statusCode': 500,
            'body': json.dumps(f"Failed to execute the function. Error: {str(e)}")
        }
