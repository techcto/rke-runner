# https://rancher.com/docs/rancher/v2.x/en/installation/ha-server-install-external-lb/
# https://rancher.com/docs/rancher/v2.x/en/upgrades/ha-server-upgrade/

import boto3,json,os,subprocess,base64,time,shutil
from botocore.vendored import requests
import paramiko

import awsasg,awslambda,awss3,lambdautils,rke,rkeetcd

#Boot up modules
awsasg = awsasg.AwsAsg(os.environ['Cluster'])
awss3 = awss3.AwsS3()
awslambda = awslambda.AwsLambda(awsasg)
lambdautils = lambdautils.LambdaUtils()
rke = rke.Rke(lambdautils)
rkeetcd = rkeetcd.RkeEtcd(lambdautils)

s3 = boto3.resource('s3')
s3Client = boto3.client('s3')

def run(event, context):

    print("Run App")
    print(event)
    print(context)
    print(os.environ)

    lambdautils._init_bin('rke')

    #Set Event Status
    awsasg.check_event_status(event, context)

    #Check is this is a new or existing rke cluster
    init(awsasg)

    #Check ASG instances to see what is going on
    awsasg.check_instance_status()

    #Generate RKE config
    print("Generate Kubernetes Cluster RKE config with all active instances")
    rkeCrts = rke.generateCertificates()
    rke.generateRKEConfig(awsasg.activeInstances, os.environ['InstanceUser'], os.environ['instancePEM'], os.environ['FQDN'], rkeCrts)

    #Run Application
    dispatcher(awsasg)

def init(awsasg):
    status = awss3.file_exists(os.environ['Bucket'], 'config.yaml')
    if status == True:
        print("Download RKE generated configs")
        s3Client.download_file(os.environ['Bucket'], 'config.yaml', '/tmp/config.yaml')
        s3Client.download_file(os.environ['Bucket'], 'kube_config_config.yaml', '/tmp/kube_config_config.yaml')
        awsasg.status = "update"

def dispatcher(asg):
    if os.environ['Status'] == "clean":
        clean(asg)
    elif asg.status == "exit":
        exit(asg)
    elif asg.status == "retry":
        retry(asg)
    elif asg.status == "backup":
        backup(asg)
        exit(asg)
    elif (asg.status == "heal" or os.environ['Status'] == "heal"):
        backup(asg)
        heal(asg)
    elif (asg.status == "update" or os.environ['Status'] == "update"):
        update(asg)
    else:
        install(asg)
    return True

def install(asg):
    print("Install Kubernetes via RKE")
    rke.rkeUp()
    print("Upload RKE generated configs")
    s3Client.upload_file('/tmp/config.yaml', os.environ['Bucket'], 'config.yaml')
    s3Client.upload_file('/tmp/kube_config_config.yaml', os.environ['Bucket'], 'kube_config_config.yaml')
    exit(asg)
    
def update(asg):
    print("Update Kubernetes via RKE")
    rke.rkeUp()
    print("Upload RKE generated configs")
    s3Client.upload_file('/tmp/config.yaml', os.environ['Bucket'], 'config.yaml')
    s3Client.upload_file('/tmp/kube_config_config.yaml', os.environ['Bucket'], 'kube_config_config.yaml')
    exit(asg)
    
def heal(asg):
    print("Upload latest snapshot to all instances")
    rkeetcd.uploadSnapshot(asg.activeInstances, os.environ['InstanceUser'])
    print("Restore instances with latest snapshot")
    restoreStatus = rkeetcd.restoreSnapshot(asg.activeInstances, os.environ['Bucket'])
    if restoreStatus == False:
        print("Restore failed!")
        print("We are going to halt the execution of this script, as running update after a failed restore will wipe your cluster!")
        print("Restart the Kubernetes components on all cluster nodes to prevent potential future etcd conflicts")
        exit(asg)
    else:
        print("Restart Kubernetes")
        rke.restartKubernetes(asg.activeInstances, os.environ['InstanceUser'])
        update(asg)

def backup(asg):
    print("Take snapshot from running healthy instaces and upload externally to S3")
    rkeetcd.takeSnapshot(asg.activeInstances, os.environ['InstanceUser'], os.environ['Bucket'])

def retry(asg):
    time.sleep(60)
    dispatcher(asg)
    return True

def exit(asg):
    print("Complete Lifecycle")
    asg.complete_lifecycle_action('CONTINUE')
    return True

def clean(asg):
    print("Clean the instances and start over.")
    rke.rkeDown(asg.activeInstances, os.environ['InstanceUser'])