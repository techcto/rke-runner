class AwsEc2:
    def __init__(self):
        print("Init AwsEc2 Class")

    # def uploadFile(instances, instanceUser):
    #     for instance in instances:
    #         print("Upload etcdbackup to each instance")
    #         try:
    #             upload_file(instance['PublicIpAddress'], instanceUser, '/tmp/etcdsnapshot', '/opt/rke/etcd-snapshots/etcdsnapshot')
    #         except BaseException as e:
    #             print(str(e))
    #             return False
    #     return True