Lambda functions written in Python to perform AWS Aurora databases
vertical autoscaling:

1. _Alarm_ (`rds_vscale_alarm_lambda.py`) is a lambda function triggered
when the CPU Load Average value exceeds a threshold. It finds a suitable
small instance within an RDS cluster and performs its scaling to
the next possible instance type.
2. _Event_ (`rds_vscale_event_lambda.py`) is a lambda function triggered
when the instance modification initiated by _Alarm_ is completed. It
scales the rest smallest RDS instances bringing them to the same size.

This code is used (and better described) in the following article:
* [“Implementing vertical autoscaling for Aurora databases using Lambda functions in AWS”](https://blog.palark.com/aws-rds-aurora-vertical-autoscaling/)
(published in April 2024)
