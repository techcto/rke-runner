import boto3,json,os,time,subprocess,base64,shutil
from botocore.vendored import requests
from io import StringIO

ec2Client = boto3.client('ec2')
autoscalingClient = boto3.client('autoscaling')
snsClient = boto3.client('sns')
lambdaClient = boto3.client('lambda')

LAMBDA_TASK_ROOT = os.environ.get('LAMBDA_TASK_ROOT', os.path.dirname(os.path.abspath(__file__)))
LIB_DIR = os.path.join(LAMBDA_TASK_ROOT, 'lib')
### In order to get permissions right, we have to copy them to /tmp
BIN_DIR = '/tmp/bin'
OPENSSL = '/usr/bin/openssl'
SUCCESS = "SUCCESS"
FAILED = "FAILED"

#Define Utility Scripts
def publishSNSMessage(snsMessage,snsTopicArn):
    response = snsClient.publish(TopicArn=snsTopicArn,Message=json.dumps(snsMessage),Subject='Rebalancing')

# This is necessary as we don't have permissions in /var/tasks/bin where the lambda function is running
def _init_bin(executable_name):
    start = time.clock()

    if not os.path.exists(BIN_DIR):
        print("Creating bin folder")
        os.makedirs(BIN_DIR)

    print("Copying binaries for "+executable_name+" in /tmp/bin")
    currfile = os.path.join(LAMBDA_TASK_ROOT, executable_name)
    newfile  = os.path.join(BIN_DIR, executable_name)
    copyResult = shutil.copyfile(currfile, newfile)
    print(copyResult)

    print("Giving new binaries permissions for lambda")
    os.chmod(newfile, 0o755)
    elapsed = (time.clock() - start)
    print(executable_name+" ready in "+str(elapsed)+'s.')

def _key_existing_size__head(client, bucket, key):
    try:
        obj = client.head_object(Bucket=bucket, Key=key)
        return obj['ContentLength']
    except BaseException as e:
            print(str(e))

def reindent(s, numSpaces):
    leading_space = numSpaces * ' '
    lines = [ leading_space + line.strip( )
              for line in s.splitlines( ) ]
    return '\n'.join(lines)

def openssl(*args):
    cmdline = [OPENSSL] + list(args)
    subprocess.check_call(cmdline)

def send(event, context, responseStatus, responseData, physicalResourceId=None, noEcho=False):
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
        response = requests.put(responseUrl,
        data=json_responseBody,
        headers=headers)
        print("Status code: " + response.reason)
    except Exception as e:
        print("send(..) failed executing requests.put(..): " + str(e))

#Start App
def getActiveInstances(asgName):
    #Step 1: Get all instances for an ASG
    filters = [{  
        'Name': 'tag:aws:autoscaling:groupName',
        'Values': [asgName]
    }]

    asgInstances={}
    for reservation in ec2Client.describe_instances(Filters=filters)['Reservations']:
        print(reservation['Instances'])
        for instance in reservation['Instances']:
            #Check to see if instance is healthy
            response = autoscalingClient.describe_auto_scaling_instances(
                InstanceIds=[
                    instance['InstanceId']
                ]
            )

            for asgInstance in response['AutoScalingInstances']:
                print("Print Instance")
                print(asgInstance)
                if asgInstance['HealthStatus'] == 'HEALTHY':   
                    asgInstances.append(instance)

    print(asgInstances)
    return asgInstances

def generateCertificates(FQDN):
    #Create CA Signing Authority
    os.environ['HOME'] = '/tmp'
    rkeS3Bucket=os.environ['rkeS3Bucket']
    openssl("version")
    s3 = boto3.resource('s3')

    try:
        s3.Object(rkeS3Bucket, 'server.crt').load()
    except BaseException as e:
        print("The certs do not exist")

        #Create CA
        openssl("req", "-new", "-newkey", "rsa:4096", "-days", "3650", "-nodes", "-subj", "/C=US/ST=Florida/L=Orlando/O=spacemade/OU=org unit/CN=spacemade.com", "-x509", "-keyout", "/tmp/ca.key", "-out", "/tmp/ca.crt")

        #Create Certificate
        openssl("req", "-new", "-newkey", "rsa:4096", "-days", "3650", "-nodes", "-subj", "/C=US/ST=Florida/L=Orlando/O=spacemade/OU=org unit/CN=" +FQDN, "-keyout", "/tmp/server.key", "-out", "/tmp/server.csr")

        #Sign the certificate from the CA
        openssl("x509", "-req", "-days", "3650", "-in", "/tmp/server.csr", "-CA", "/tmp/ca.crt", "-CAkey", "/tmp/ca.key", "-set_serial", "01", "-out", "/tmp/server.crt")

        #Upload certs to s3
        try:
            print("Upload certs to S3")
            s3.meta.client.upload_file('/tmp/server.crt', rkeS3Bucket, 'server.crt')
            s3.meta.client.upload_file('/tmp/server.key', rkeS3Bucket, 'server.key')
            s3.meta.client.upload_file('/tmp/ca.crt', rkeS3Bucket, 'ca.crt')
        except BaseException as e:
            print(str(e))
    else:
        s3.meta.client.download_file(rkeS3Bucket, 'server.crt', '/tmp/server.crt')
        s3.meta.client.download_file(rkeS3Bucket, 'server.key', '/tmp/server.key')
        s3.meta.client.download_file(rkeS3Bucket, 'ca.crt', '/tmp/ca.crt')

    rkeCrts={}

    #read cert file
    with open("/tmp/server.crt", "rb") as crt:
        rkeCrts['crt'] = base64.b64encode(crt.read())

    #read key file
    with open("/tmp/server.key", "rb") as key:
        rkeCrts['key'] = base64.b64encode(key.read())

    #read ca file
    with open("/tmp/ca.crt", "rb") as ca:
        rkeCrts['ca'] = base64.b64encode(ca.read())

    return rkeCrts

def generateRKEConfig(asgInstances, instanceUser, instancePEM, FQDN, rkeCrts):

    rkeConfig = ('# default k8s version: v1.8.9-rancher1-1\n'
                '# default network plugin: flannel\n'
                '\n'
                'ignore_docker_version: true\n'
                '\n'
                'nodes:\n')

    for instance in asgInstances:
        print(instance)
        rkeConfig += ('  - address: ' + instance['PublicIpAddress'] + '\n'
                        '    user: ' + instanceUser + '\n'
                        '    role: [controlplane,etcd,worker]\n'
                        '    ssh_key: |- \n')
        rkeConfig += reindent(instancePEM, 8)
        rkeConfig += '\n'

    print("Finalize config yaml")
    rkeConfig += ('\n'
    'addons: |-\n'
    '   ---\n'
    '   kind: Namespace\n'
    '   apiVersion: v1\n'
    '   metadata:\n'
    '     name: cattle-system\n'
    '   ---\n'
    '   kind: ServiceAccount\n'
    '   apiVersion: v1\n'
    '   metadata:\n'
    '     name: cattle-admin\n'
    '     namespace: cattle-system\n'
    '   ---\n'
    '   kind: ClusterRoleBinding\n'
    '   apiVersion: rbac.authorization.k8s.io/v1\n'
    '   metadata:\n'
    '     name: cattle-crb\n'
    '     namespace: cattle-system\n'
    '   subjects:\n'
    '   - kind: ServiceAccount\n'
    '     name: cattle-admin\n'
    '     namespace: cattle-system\n'
    '   roleRef:\n'
    '     kind: ClusterRole\n'
    '     name: cluster-admin\n'
    '     apiGroup: rbac.authorization.k8s.io\n'
    '   ---\n'
    '   apiVersion: v1\n'
    '   kind: Secret\n'
    '   metadata:\n'
    '     name: cattle-keys-ingress\n'
    '     namespace: cattle-system\n'
    '   type: Opaque\n'
    '   data:\n'
    '     tls.crt: ' + rkeCrts['crt'].decode('utf8') + '\n'
    '     tls.key: ' + rkeCrts['key'].decode('utf8') + '\n'
    '   ---\n'
    '   apiVersion: v1\n'
    '   kind: Secret\n'
    '   metadata:\n'
    '     name: cattle-keys-server\n'
    '     namespace: cattle-system\n'
    '   type: Opaque\n'
    '   data:\n'
    '     cacerts.pem: ' + rkeCrts['ca'].decode('utf8') + '\n'
    '   ---\n'
    '   apiVersion: v1\n'
    '   kind: Service\n'
    '   metadata:\n'
    '     namespace: cattle-system\n'
    '     name: cattle-service\n'
    '     labels:\n'
    '       app: cattle\n'
    '   spec:\n'
    '     ports:\n'
    '     - port: 80\n'
    '       targetPort: 80\n'
    '       protocol: TCP\n'
    '       name: http\n'
    '     - port: 443\n'
    '       targetPort: 443\n'
    '       protocol: TCP\n'
    '       name: https\n'
    '     selector:\n'
    '       app: cattle\n'
    '   ---\n'
    '   apiVersion: extensions/v1beta1\n'
    '   kind: Ingress\n'
    '   metadata:\n'
    '     namespace: cattle-system\n'
    '     name: cattle-ingress-http\n'
    '     annotations:\n'
    '       nginx.ingress.kubernetes.io/proxy-connect-timeout: "30"\n'
    '       nginx.ingress.kubernetes.io/proxy-read-timeout: "1800"\n'
    '       nginx.ingress.kubernetes.io/proxy-send-timeout: "1800"\n'
    '   spec:\n'
    '     rules:\n'
    '     - host: ' + str(FQDN) + '\n'
    '       http:\n'
    '         paths:\n'
    '         - backend:\n'
    '             serviceName: cattle-service\n'
    '             servicePort: 80\n'
    '     tls:\n'
    '     - secretName: cattle-keys-ingress\n'
    '       hosts:\n'
    '       - ' + str(FQDN) + '\n'
    '   ---\n'
    '   kind: Deployment\n'
    '   apiVersion: extensions/v1beta1\n'
    '   metadata:\n'
    '     namespace: cattle-system\n'
    '     name: cattle\n'
    '   spec:\n'
    '     replicas: 1\n'
    '     template:\n'
    '       metadata:\n'
    '         labels:\n'
    '           app: cattle\n'
    '       spec:\n'
    '         serviceAccountName: cattle-admin\n'
    '         containers:\n'
    '         - image: rancher/rancher:latest\n'
    '           imagePullPolicy: Always\n'
    '           name: cattle-server\n'
    '           ports:\n'
    '           - containerPort: 80\n'
    '             protocol: TCP\n'
    '           - containerPort: 443\n'
    '             protocol: TCP\n'
    '           volumeMounts:\n'
    '           - mountPath: /etc/rancher/ssl\n'
    '             name: cattle-keys-volume\n'
    '             readOnly: true\n'
    '         volumes:\n'
    '         - name: cattle-keys-volume\n'
    '           secret:\n'
    '             defaultMode: 420\n'
    '             secretName: cattle-keys-server')

    outF = open('/tmp/config.yaml', 'w')
    outF.write(rkeConfig)
    outF.close()

def bucket_folder_exists(client, bucket, path_prefix):
    # make path_prefix exact match and not path/to/folder*
    if list(path_prefix)[-1] is not '/':
        path_prefix += '/'

    # check if 'Contents' key exist in response dict - if it exist it indicate the folder exists, otherwise response will be None.
    response = client.list_objects_v2(Bucket=bucket, Prefix=path_prefix).get('Contents')

    if response:
        return True
    return False

def run(event, context):
    instanceUser=os.environ['InstanceUser']
    FQDN=os.environ['FQDN']
    rkeS3Bucket=os.environ['rkeS3Bucket']
    asgName=os.environ['CLUSTER']
    pendingEc2s=0
    responseData = {}

    #Download Instance RSA Key from S3
    s3 = boto3.resource('s3')
    s3.meta.client.download_file(rkeS3Bucket, 'rsa.pem', '/tmp/rsa.pem')
    with open("/tmp/rsa.pem", "rb") as rsa:
        instancePEM = rsa.read().decode("utf-8")

    #Execute series of try/catches to deal with two different ways to call Lambda (SNS/Manually)
    try:
        snsTopicArn=event['Records'][0]['Sns']['TopicArn']
        snsMessage=json.loads(event['Records'][0]['Sns']['Message'])
        lifecycleHookName=snsMessage['LifecycleHookName']
        lifecycleActionToken=snsMessage['LifecycleActionToken']
        print("snsMessage")
        print(snsMessage)
    except BaseException as e:
        print(str(e))

    #Get active instances
    asgInstances = getActiveInstances(asgName)

    #Generate / Get certificates
    rkeCrts = generateCertificates(FQDN)

    #Generate RKE required config.yaml
    print("Create RKE config")
    generateRKEConfig(asgInstances,instanceUser,instancePEM,FQDN,rkeCrts)

    try:
        print("Upload RKE config to S3")
        s3.meta.client.upload_file('/tmp/config.yaml', rkeS3Bucket, 'config.yaml')

        try:
            #Need to test if servers actually change since last time.  Rke takes a while to run.
            print("Run RKE")
            _init_bin('rke')
            cmdline = [os.path.join(BIN_DIR, 'rke'), 'up', '--config', '/tmp/config.yaml']
            subprocess.check_call(cmdline, shell=False, stderr=subprocess.STDOUT)
            try:
                #If Lambda executed from Lifecycle Event, issue success command
                print("Complete Lifecycle Event")
                response = autoscalingClient.complete_lifecycle_action(LifecycleHookName=lifecycleHookName,AutoScalingGroupName=asgName,LifecycleActionToken=lifecycleActionToken,LifecycleActionResult='CONTINUE')
            except BaseException as e:
                print(str(e))
                #Else if executed from Cloudformation or elsewhere, return true.
                responseData['status'] = "success"
                try:
                    print("Tell Cloudformation we are good!")
                    send(event, context, SUCCESS, responseData)
                except BaseException as e:
                    print(str(e))
                    return False
        except BaseException as e:
            print("Something went wrong!  Wait 15 seconds and try again.")
            time.sleep(15)
            try:
                publishSNSMessage(snsMessage,snsTopicArn)
            except BaseException as e:
                print(str(e))
    except BaseException as e:
        print(str(e))
        return False