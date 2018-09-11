import boto3

class AwsS3:
    def __init__(self):
        print("Init AwsS3 Class")
        self.s3Client = boto3.resource('s3')

    def key_existing_size__head(self, bucket, key):
        try:
            obj = self.s3Client.head_object(Bucket=bucket, Key=key)
            return obj['ContentLength']
        except BaseException as e:
                print(str(e))

    def bucket_folder_exists(self, bucket, path_prefix):
        # make path_prefix exact match and not path/to/folder*
        if list(path_prefix)[-1] is not '/':
            path_prefix += '/'

        # check if 'Contents' key exist in response dict - if it exist it indicate the folder exists, otherwise response will be None.
        response = self.s3Client.list_objects_v2(Bucket=bucket, Prefix=path_prefix).get('Contents')

        if response:
            return True
        return False

    def file_exists(self, bucket, key):
        try:
            self.s3Client.Object(bucket, key).load()
        except BaseException as e:
            print("File " + key + " does not exist in bucket " + bucket)
            print(str(e))
            return False
        else:
            print("Success: " + key + " does exist in bucket " + bucket) 
            return True

    def download_file(self, bucket, key):
        print("Copy "+key+" from S3 to local /tmp/"+key)
        self.s3Client.download_file(bucket, key, '/tmp/'+key)
        with open('/tmp/'+key, "rb") as file:
            contents = file.read().decode("utf-8")

        return contents