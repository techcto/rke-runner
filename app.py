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

    #Run Application
    dispatcher(os.environ, awsasg)

def init(awsasg):
    status = awss3.file_exists(os.environ['Bucket'], 'config.yaml')
    if status == True:
        print("Download RKE generated configs")
        s3Client.download_file(os.environ['Bucket'], 'config.yaml', '/tmp/config.yaml')
        s3Client.download_file(os.environ['Bucket'], 'kube_config_config.yaml', '/tmp/kube_config_config.yaml')
        awsasg.status = "update"

def dispatcher(env, asg):
    if env.Status == "clean":
        clean(env, asg)
    elif asg.status == "exit":
        exit(env, asg)
    elif asg.status == "retry":
        retry(env, asg)
    elif asg.status == "backup":
        backup(env, asg)
    elif asg.status == "restore":
        restore(env, asg)
    elif asg.status == "update":
        update(env, asg)
    else:
        install(env, asg)
    return True

def install(env, asg):
    print("Generate certificates")
    rkeCrts = rke.generateCertificates()
    print("Generate Kubernetes Cluster RKE config with all active instances")
    rke.generateRKEConfig(awsasg.activeInstances, os.environ['InstanceUser'], os.environ['instancePEM'], os.environ['FQDN'], rkeCrts)
    print("Install Kubernetes via RKE")
    rke.rkeUp()
    print("Upload RKE generated configs")
    s3Client.upload_file('/tmp/config.yaml', os.environ['Bucket'], 'config.yaml')
    s3Client.upload_file('/tmp/kube_config_config.yaml', env['Bucket'], 'kube_config_config.yaml')
    exit(env, asg)
    
def update(env, asg):
    print("Update Kubernetes via RKE")
    rke.rkeUp()
    print("Upload RKE generated configs")
    s3Client.upload_file('/tmp/config.yaml', os.environ['Bucket'], 'config.yaml')
    s3Client.upload_file('/tmp/kube_config_config.yaml', env['Bucket'], 'kube_config_config.yaml')
    exit(env, asg)
    
def restore(env, asg):
    print("Upload latest snapshot to all instances")
    rkeetcd.uploadSnapshot(asg.activeInstances, env['InstanceUser'])
    print("Generate Kubernetes Cluster RKE config with all active instances")
    rkeCrts = rke.generateCertificates()
    rke.generateRKEConfig(awsasg.activeInstances, os.environ['InstanceUser'], os.environ['instancePEM'], os.environ['FQDN'], rkeCrts)
    print("Restore instances with latest snapshot")
    restoreStatus = rkeetcd.restoreSnapshot(asg.activeInstances, env['Bucket'])
    if restoreStatus == False:
        print("Restore failed!")
        print("We are going to halt the execution of this script, as running update after a failed restore will wipe your cluster!")
        print("Restart the Kubernetes components on all cluster nodes to prevent potential future etcd conflicts")
        exit(env, asg)
    else:
        print("Restart Kubernetes")
        rke.restartKubernetes(asg.activeInstances, env['InstanceUser'])
        update(env, asg)

def backup(env, asg):
    print("Take snapshot from running healthy instaces and upload externally to S3")
    rkeetcd.takeSnapshot(asg.activeInstances, env['InstanceUser'], env['Bucket'])

def retry(env, asg):
    time.sleep(60)
    dispatcher(env, asg)
    return True

def exit(env, asg):
    print("Complete Lifecycle")
    asg.complete_lifecycle_action('CONTINUE')
    return True

def clean(env, asg):
    print("Clean the instances and start over.")
    rke.rkeDown(asg.activeInstances, env['InstanceUser'])