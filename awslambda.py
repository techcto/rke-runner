import boto3,json,os
from botocore.vendored import requests

responseData = {}
SUCCESS = "SUCCESS"
FAILED = "FAILED"

class AwsLambda:
    def __init__(self, asg):
        print("Init AwsLambda Class")
        self.asg = asg
        self.snsClient = boto3.client('sns')
        self.s3Client = boto3.resource('s3')

    def publish_sns_message(self, subject):
        try:
            self.snsClient.publish(TopicArn=self.asg.snsTopicArn,Message=json.dumps(self.asg.snsMessage),Subject=subject)
            return True
        except Exception as e:
            print("SNS message not supported:" + str(e))
            responseData['status'] = "success"
            try:
                print("Tell Cloudformation we are good!")
                self.send_response(self.asg.event, self.asg.context, SUCCESS, responseData)
            except BaseException as e:
                return False
            return False

    def send_response(self, event, context, responseStatus, responseData, physicalResourceId=None, noEcho=False):
        responseUrl = event['ResponseURL']

        print(responseUrl)

        responseBody = {}
        responseBody['Status'] = responseStatus
        responseBody['Reason'] = 'See the details in CloudWatch Log Stream: ' + context.log_stream_name
        responseBody['PhysicalResourceId'] = physicalResourceId or context.log_stream_name
        responseBody['StackId'] = event['StackId']
        responseBody['RequestId'] = event['RequestId']
        responseBody['LogicalResourceId'] = event['LogicalResourceId']
        responseBody['NoEcho'] = noEcho
        responseBody['Data'] = responseData

        json_responseBody = json.dumps(responseBody)

        print("Response body:\n" + json_responseBody)

        headers = {
            'content-type' : '',
            'content-length' : str(len(json_responseBody))
        }

        try:
            response = requests.put(responseUrl, data=json_responseBody, headers=headers)
            print("Status code: " + response.reason)
        except Exception as e:
            print("send(..) failed executing requests.put(..): " + str(e))