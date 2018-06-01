import boto3,json,os,time,subprocess,base64
from io import StringIO

ec2Client = boto3.client('ec2')
autoscalingClient = boto3.client('autoscaling')
snsClient = boto3.client('sns')
lambdaClient = boto3.client('lambda')

OPENSSL = '/usr/bin/openssl'

def publishSNSMessage(snsMessage,snsTopicArn):
    response = snsClient.publish(TopicArn=snsTopicArn,Message=json.dumps(snsMessage),Subject='Rebalancing')

def openssl(*args):
    cmdline = [OPENSSL] + list(args)
    subprocess.check_call(cmdline)

def checkEc2s(asgName):
    filters = [{  
    'Name': 'tag:aws:autoscaling:groupName',
    'Values': [asgName]
    }]
    ec2ContainerInstances = ec2Client.describe_instances(Filters=filters)
    print(str(ec2ContainerInstances))
    pendingEc2s = 0
    activeEc2s = 0
    for i in range(len(ec2ContainerInstances['Reservations'])):
        instance = ec2ContainerInstances['Reservations'][i]['Instances'][0]
        print(str(instance['State']['Name']))
        print(str(instance))
        if instance['State']['Name'] == 'disabling':
            pendingEc2s = pendingEc2s + 1
        elif instance['State']['Name'] == 'pending':
            pendingEc2s = pendingEc2s + 1
        elif instance['State']['Name'] == 'running':
            activeEc2s = activeEc2s + 1
    print("Active EC2s: ",activeEc2s)
    return pendingEc2s

def generateCertificates(FQDN):
    #Create CA Signing Authority
    os.environ['HOME'] = '/tmp'

    openssl("version")
    
    #Create CA
    openssl("req", "-new", "-newkey", "rsa:4096", "-days", "3650", "-nodes", "-subj", "/C=US/ST=Florida/L=Orlando/O=spacemade/OU=org unit/CN=spacemade.com", "-x509", "-keyout", "/tmp/ca.key", "-out", "/tmp/ca.crt")

    #Create Certificate
    openssl("req", "-new", "-newkey", "rsa:4096", "-days", "3650", "-nodes", "-subj", "/C=US/ST=Florida/L=Orlando/O=spacemade/OU=org unit/CN=" +FQDN, "-keyout", "/tmp/server.key", "-out", "/tmp/server.csr")

    #Sign the certificate from the CA
    openssl("x509", "-req", "-days", "3650", "-in", "/tmp/server.csr", "-CA", "/tmp/ca.crt", "-CAkey", "/tmp/ca.key", "-set_serial", "01", "-out", "/tmp/server.crt")

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

def generateRKEConfig(asgName, instanceUser, keyName, FQDN, rkeCrts):
    print("FQDN: " + FQDN)
    filters = [{  
    'Name': 'tag:aws:autoscaling:groupName',
    'Values': [asgName]
    }]
    ec2ContainerInstances = ec2Client.describe_instances(Filters=filters)

    rkeConfig = ('# default k8s version: v1.8.9-rancher1-1\n'
                '# default network plugin: flannel\n'
                'ignore_docker_version: true\n'
                '\n'
                'nodes:\n')

    for i in range(len(ec2ContainerInstances['Reservations'])):
        instance = ec2ContainerInstances['Reservations'][i]['Instances'][0]
        if instance['State']['Name'] == 'running':
            rkeConfig += (' - address: ' + instance['PublicIpAddress'] + '\n'
                                '   user: ' + instanceUser + '\n'
                                '   role: [controlplane,etcd,worker]\n'
                                '   ssh_key_path: ' + keyName + '\n')

    rkeConfig += ('\n'
    'addons: |-\n'
    '   ---\n'
    '   kind: Namespace\n'
    '   apiVersion: v1\n'
    '   metadata:\n'
    '       name: cattle-system\n'
    '   ---\n'
    '   kind: ServiceAccount\n'
    '   apiVersion: v1\n'
    '   metadata:\n'
    '       name: cattle-admin\n'
    '       namespace: cattle-system\n'
    '   ---\n'
    '   kind: ClusterRoleBinding\n'
    '   apiVersion: rbac.authorization.k8s.io/v1\n'
    '   metadata:\n'
    '       name: cattle-crb\n'
    '       namespace: cattle-system\n'
    '   subjects:\n'
    '   - kind: ServiceAccount\n'
    '       name: cattle-admin\n'
    '       namespace: cattle-system\n'
    '   roleRef:\n'
    '       kind: ClusterRole\n'
    '       name: cluster-admin\n'
    '    apiGroup: rbac.authorization.k8s.io\n'
    '   ---\n'
    '   apiVersion: v1\n'
    '   kind: Secret\n'
    '   metadata:\n'
    '       name: cattle-keys-ingress\n'
    '       namespace: cattle-system\n'
    '   type: Opaque\n'
    '   data:\n'
    '       tls.crt: ' + str(rkeCrts['crt']) + '\n'
    '       tls.key: ' + str(rkeCrts['key']) + '\n'
    '   ---\n'
    '   apiVersion: v1\n'
    '   kind: Secret\n'
    '   metadata:\n'
    '       name: cattle-keys-server\n'
    '       namespace: cattle-system\n'
    '   type: Opaque\n'
    '   data:\n'
    '       cacerts.pem: ' + str(rkeCrts['ca']) + '\n'
    '   ---\n'
    '   apiVersion: v1\n'
    '   kind: Service\n'
    '   metadata:\n'
    '       namespace: cattle-system\n'
    '       name: cattle-service\n'
    '       labels:\n'
    '       app: cattle\n'
    '   spec:\n'
    '       ports:\n'
    '       - port: 80\n'
    '       targetPort: 80\n'
    '       protocol: TCP\n'
    '       name: http\n'
    '       - port: 443\n'
    '       targetPort: 443\n'
    '       protocol: TCP\n'
    '       name: https\n'
    '       selector:\n'
    '       app: cattle\n'
    '   ---\n'
    '   apiVersion: extensions/v1beta1\n'
    '   kind: Ingress\n'
    '   metadata:\n'
    '       namespace: cattle-system\n'
    '       name: cattle-ingress-http\n'
    '       annotations:\n'
    '       nginx.ingress.kubernetes.io/proxy-connect-timeout: 30\n'
    '       nginx.ingress.kubernetes.io/proxy-read-timeout: 1800\n'
    '       nginx.ingress.kubernetes.io/proxy-send-timeout: 1800\n'
    '   spec:\n'
    '       rules:\n'
    '       - host: ' + str(FQDN) + '\n'
    '       http:\n'
    '           paths:\n'
    '           - backend:\n'
    '               serviceName: cattle-service\n'
    '               servicePort: 80\n'
    '       tls:\n'
    '       - secretName: cattle-keys-ingress\n'
    '       hosts:\n'
    '       - ' + str(FQDN) + '\n'
    '   ---\n'
    '   kind: Deployment\n'
    '   apiVersion: extensions/v1beta1\n'
    '   metadata:\n'
    '       namespace: cattle-system\n'
    '       name: cattle\n'
    '   spec:\n'
    '       replicas: 1\n'
    '       template:\n'
    '       metadata:\n'
    '           labels:\n'
    '           app: cattle\n'
    '       spec:\n'
    '           serviceAccountName: cattle-admin\n'
    '           containers:\n'
    '           - image: rancher/rancher:latest\n'
    '           imagePullPolicy: Always\n'
    '           name: cattle-server\n'
    '           ports:\n'
    '           - containerPort: 80\n'
    '            protocol: TCP\n'
    '           - containerPort: 443\n'
    '               protocol: TCP\n'
    '           volumeMounts:\n'
    '           - mountPath: /etc/rancher/ssl\n'
    '               name: cattle-keys-volume\n'
    '               readOnly: true\n'
    '           volumes:\n'
    '        - name: cattle-keys-volume\n'
    '           secret:\n'
    '               defaultMode: 420\n'
    '               secretName: cattle-keys-server')

    outF = open('/tmp/config.yaml', 'w')
    outF.write(rkeConfig)
    outF.close()

def bucket_folder_exists(client, bucket, path_prefix):
    # make path_prefix exact match and not path/to/folder*
    if list(path_prefix)[-1] is not '/':
        path_prefix += '/'

    # check if 'Contents' key exist in response dict - if it exist it indicate the folder exists, otherwise response will be None
    response = client.list_objects_v2(Bucket=bucket, Prefix=path_prefix).get('Contents')

    if response:
        return True
    return False

def run(event, context):
    instanceUser=os.environ['InstanceUser']
    keyName=os.environ['KeyName']
    FQDN=os.environ['FQDN']
    rkeS3Bucket=os.environ['rkeS3Bucket']
    asgName=os.environ['CLUSTER']
    pendingEc2s=0

    try:
        snsTopicArn=event['Records'][0]['Sns']['TopicArn']
        snsMessage=json.loads(event['Records'][0]['Sns']['Message'])
        lifecycleHookName=snsMessage['LifecycleHookName']
        lifecycleActionToken=snsMessage['LifecycleActionToken']
    except BaseException as e:
        print(str(e))

    pendingEc2s=checkEc2s(asgName);

    if pendingEc2s==0:
        rkeCrts = generateCertificates(FQDN)
        print("Create RKE config")
        generateRKEConfig(asgName,instanceUser,keyName,FQDN,rkeCrts)
        try:
            print("Upload RKE config to S3")
            s3 = boto3.resource('s3')
            s3.meta.client.upload_file('/tmp/config.yaml', rkeS3Bucket, 'config.yaml')

            try:
                print("Run RKE")
                subprocess.check_call(["mv", "-f", "rke", "/tmp/rke"], shell=True)
                subprocess.check_call(["chmod", "+x", "/tmp/rke"], shell=True)
                subprocess.check_call(["/tmp/rke", "up", "--config", "/tmp/config.yaml"], shell=True)

                try:
                    print("Complete Lifecycle Event")
                    response = autoscalingClient.complete_lifecycle_action(LifecycleHookName=lifecycleHookName,AutoScalingGroupName=asgName,LifecycleActionToken=lifecycleActionToken,LifecycleActionResult='CONTINUE')
                except BaseException as e:
                    print(str(e))
            except BaseException as e:
                print(str(e))
        except BaseException as e:
            print(str(e))
    elif pendingEc2s>=1:
        time.sleep(5)
        try:
            publishSNSMessage(snsMessage,snsTopicArn)
        except BaseException as e:
                print(str(e))