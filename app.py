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
rke = rke.Rke()
rkeetcd = rkeetcd.RkeEtcd()

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

    #Set ASG Status
    awsasg.check_instance_status()

    #Check RKE Status
    rkeStatus = awss3.file_exists(os.environ['Bucket'], 'config.yaml')

    #Run Application
    dispatcher(os.environ, awsasg, rkeStatus);

    return True

def dispatcher(env, asg, rkeStatus):
    if os.environ['Clean'] == "True":
        rke.rkeDown()
        # install(env, asg)
    elif rkeStatus == True:
        backup(env, asg)
    elif asg.snsSubject == "restore":
        restore(env, asg)
    elif asg.snsSubject == "update":
        update(env, asg)
    elif asg.status == "exit":
        exit(env, asg)
    elif asg.status == "retry":
        retry(env, asg)
    else:
        install(env, asg)
    return True

def install(env, asg):
    print("Generate certificates")
    rkeCrts = rke.generateCertificates()
    print("Generate Kubernetes Cluster RKE config with all active instances")
    rke.generateRKEConfig(asg.activeInstances,env['InstanceUser'],os.environ['instancePEM'],env['FQDN'],rkeCrts)
    print("Upload generated config file to S3 for backup")
    s3Client.upload_file('/tmp/config.yaml', env['Bucket'], 'config.yaml')
    print("Install Kubernetes via RKE")
    rke.rkeUp()
    print("Upload RKE generated config")
    s3Client.upload_file('/tmp/kube_config_config.yaml', env['Bucket'], 'kube_config_config.yaml')
    print("Complete Lifecycle")
    asg.complete_lifecycle_action('CONTINUE')
    exit(env, asg)
    
def update(env, asg):
    print("Get certificates")
    rkeCrts = rke.getCertificates()
    print("Download RKE generated config")
    s3Client.download_file(env['Bucket'], 'kube_config_config.yaml', '/tmp/kube_config_config.yaml')
    print("Generate Kubernetes Cluster RKE config with all active instances")
    rke.generateRKEConfig(asg.activeInstances,env['InstanceUser'],os.environ['instancePEM'],env['FQDN'],rkeCrts)
    print("Upload generated config file to S3 for backup")
    s3Client.upload_file('/tmp/config.yaml', env['Bucket'], 'config.yaml')
    print("Update Kubernetes via RKE")
    rke.rkeUp()
    print("Upload RKE generated config")
    s3Client.upload_file('/tmp/kube_config_config.yaml', env['Bucket'], 'kube_config_config.yaml')
    exit(env, asg)
    
def backup(env, asg):
    print("Take snapshot from running healthy instaces and upload externally to S3")
    rkeetcd.takeSnapshot(asg.activeInstances, env['Bucket'])
    status = awslambda.publish_sns_message("restore")
    if status == False:
        restore(env, asg)
    
def restore(env, asg):
    print("Upload latest snapshot to all instances")
    uploadSnapshotStatus = rkeetcd.uploadSnapshot(asg.activeInstances, env['InstanceUser'])
    if uploadSnapshotStatus:
        print("Restore instances with latest snapshot")
        restoreStatus = rkeetcd.restoreSnapshot(asg.activeInstances, env['Bucket'])
        rke.restartKubernetes(asg.activeInstances, env['InstanceUser'])
        if restoreStatus == False:
            print("Restore failed!")
            print("We are going to halt the execution of this script, as running update after a failed restore will wipe your cluster!")
            print("Restart the Kubernetes components on all cluster nodes to prevent potential future etcd conflicts")
            exit(env, asg)
        else:
            print("Call Update Function via SNS")
            status = awslambda.publish_sns_message("update")
            if status == False:
                update(env, asg)

def exit(env, asg):
    print("Complete Lifecycle")
    asg.complete_lifecycle_action('CONTINUE')
    return True

def retry(env, asg):
    time.sleep(15)
    status = awslambda.publish_sns_message()
    if status == False:
        install(env, asg)
    return True