## RKE Runner (Script to run RKE to install and manage kubernetes on AWS)

To use RKE runner:

- Download / clone this repo
- Install Paramiko
    - pip install paramiko
- Rename env.json.dist to env.json and fill in values
    - Cluster: This is the AutoScalingGroup name that you have at AWS
    - FQDN: This is the URL that you would like RKE to use when generating the Kubernetes cluster
    - InstanceUser: This is the user RKE runner will generate for you to manage the AWS instances
    - Bucket: This is the S3 bucket where RKE runner will use to store important information needed to manage your Kubernetes cluster
    - Status: Leave this blank unless you want to clean / scrub your instances.  If so, set to "clean"
- Set permissions for cmd.sh to 700
- Execute:  ./cmd rkeUpdate
    - If this is a fresh install, RKE runner will detect this and install Ramcher 2.0
    - If this is a previous install, RKE runner will also detect this and then execute:
        - Backup
        - Restore
        - Update