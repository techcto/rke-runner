import boto3,os,subprocess,base64
s3Client = boto3.client('s3')

BIN_DIR = '/tmp/bin'

class RkeEtcd:
    def __init__(self, lambdautils):
        print("Init ETCDRKE Class")
        self.lambdautils = lambdautils
        self.s3Client = boto3.client('s3')

    def takeSnapshot(self, instances, username, bucket):
        try:
            print("ETCD is attempting to be backed up")
            cmdline = [os.path.join(BIN_DIR, 'rke'), 'etcd', 'snapshot-save', '--name', 'etcdsnapshot', '--config', '/tmp/config.yaml']
            subprocess.check_call(cmdline, shell=False, stderr=subprocess.STDOUT) 
            print("ETCD has been successfully backed up to /opt/rke/etcd-snapshots/etcdsnapshot on the running kubernetes instance")

            for instance in instances:
                try:
                    print("Login to ETCD instance and copy backup to local /tmp for Lambda")
                    self.lambdautils.download_file(instance['PublicIpAddress'], username, '/opt/rke/etcd-snapshots/etcdsnapshot', '/tmp/etcdsnapshot')
                    print("Upload snapshot to S3")
                    self.s3Client.upload_file('/tmp/etcdsnapshot', bucket, 'etcdsnapshot')
                except BaseException as e:
                    print(str(e))
            return True
            
        except BaseException as e:
            print(str(e))
            print("ETCD backup failed.  Most likely this is a new cluster or a new instance was added and cannot be healed")

            try:
                print("Try to recover backup from S3")
                self.s3Client.download_file(bucket, 'etcdsnapshot', '/tmp/etcdsnapshot')
                return True
            except BaseException as e:
                print("No go.  Good luck.  I hope you have other backups.")
                return False

    def uploadSnapshot(self, instances, username):
        for instance in instances:
            print("Upload etcdbackup to each instance")
            try:
                self.lambdautils.upload_file(instance['PublicIpAddress'], username, '/tmp/etcdsnapshot', '/opt/rke/etcd-snapshots/etcdsnapshot')
            except BaseException as e:
                print ("Error: We were unable to upload the backup" + str(e))
                return False
        return True

    def restoreSnapshot(self, instances, bucket):
        if os.path.isfile('/tmp/etcdsnapshot'):
            try:
                print("Restore ETCD snapshot")
                cmdline = [os.path.join(BIN_DIR, 'rke'), 'etcd', 'snapshot-restore', '--name', 'etcdsnapshot', '--config', '/tmp/config.yaml']
                subprocess.check_call(cmdline, shell=False, stderr=subprocess.STDOUT) 
                return True
            except BaseException as e:
                print(str(e))
                return False