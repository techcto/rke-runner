## RKE Runner (Script to run RKE to install and manage kubernetes on AWS)

To use RKE runner:

- Download / clone this repo
- ./rke.sh init
- Rename .env.dist to .env and fill in values
    - Cluster: This is the AutoScalingGroup name that you have at AWS - ie: rancher26-EC2-1KNOLF3VC5UD3-EC2AutoScalingGroup-1QKDS1URH0K5B
    - FQDN: This is the URL that you would like RKE to use when generating the Kubernetes cluster - ie: rancher2.spce.io
    - InstanceUser: This is the user RKE runner will generate for you to manage the AWS instances
    - Bucket: This is the S3 bucket where RKE runner will use to store important information needed to manage your Kubernetes cluster - ie: rancher26-rke
    - Status: Leave this blank unless you want to clean / scrub your instances.  If so, set to "clean"
- Set permissions for rke.sh to 700
- ./rke.sh run