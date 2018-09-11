import boto3,os,subprocess,base64
import lambdautils

from subprocess import Popen,PIPE

BIN_DIR = '/tmp/bin'

class Rke:
    def __init__(self, lambdautils):
        print("Init RKE Class")
        self.lambdautils = lambdautils
        self.s3Client = boto3.client('s3')
        self.s3 = boto3.resource('s3')

    def rkeDown(self, instances, username):
        print("RKE Wipe Cluster")
        cmdline = [os.path.join(BIN_DIR, 'rke'), 'remove', '--config', '/tmp/config.yaml']
        rke_proc = Popen(cmdline, shell=False, stdin=PIPE, stderr=subprocess.STDOUT)
        rke_proc.communicate(b'Y\n')
        print("Finish Wiping and Install New Cluster")

        commands = [
            'docker rm -f $(docker ps -qa)',
            'docker volume rm $(docker volume ls -q)',
            'cleanupdirs="/var/lib/etcd /etc/kubernetes /etc/cni /opt/cni /var/lib/cni /var/run/calico /opt/rke"',
            'for dir in $cleanupdirs; do echo "Removing $dir"; rm -rf $dir; done'
        ]
        for instance in instances:
            self.lambdautils.execute_cmd(instance['PublicIpAddress'], username, commands)
        print("Finish Running Cleanup Script")

    def rkeUp(self):
        print("Start: RKE / Update Cluster")
        cmdline = [os.path.join(BIN_DIR, 'rke'), 'up', '--config', '/tmp/config.yaml']
        subprocess.check_call(cmdline, shell=False, stderr=subprocess.STDOUT)
        print("Finish: RKE / Update Cluster")

    def restartKubernetes(self, instances, username):
        commands = [
            'docker stop etcd-rolling-snapshots',
            'docker restart kube-apiserver kubelet kube-controller-manager kube-scheduler kube-proxy',
            'docker ps | grep flannel | cut -f 1 -d " " | xargs docker restart',
            'docker ps | grep calico | cut -f 1 -d " " | xargs docker restart'
        ]

        for instance in instances:
            self.lambdautils.execute_cmd(instance['PublicIpAddress'], username, commands)
            
    def getCertificates(self):
        return self.generateCertificates()

    def generateCertificates(self):
        #Create CA Signing Authority
        os.environ['HOME'] = '/tmp'
        Bucket=os.environ['Bucket']
        FQDN=os.environ['FQDN']
        self.lambdautils.openssl("version")

        try:
            self.s3.Object(Bucket, 'server.crt').load()
        except BaseException as e:
            print("Generate a new set of ssl certificates")

            #Create CA
            self.lambdautils.openssl("req", "-new", "-newkey", "rsa:4096", "-days", "3650", "-nodes", "-subj", "/C=US/ST=Florida/L=Orlando/O=spacemade/OU=org unit/CN=spacemade.com", "-x509", "-keyout", "/tmp/ca.key", "-out", "/tmp/ca.crt")

            #Create Certificate
            self.lambdautils.openssl("req", "-new", "-newkey", "rsa:4096", "-days", "3650", "-nodes", "-subj", "/C=US/ST=Florida/L=Orlando/O=spacemade/OU=org unit/CN=" +FQDN, "-keyout", "/tmp/server.key", "-out", "/tmp/server.csr")

            #Sign the certificate from the CA
            self.lambdautils.openssl("x509", "-req", "-days", "3650", "-in", "/tmp/server.csr", "-CA", "/tmp/ca.crt", "-CAkey", "/tmp/ca.key", "-set_serial", "01", "-out", "/tmp/server.crt")

            #Upload certs to s3
            try:
                print("Upload certs to S3")
                self.s3Client.upload_file('/tmp/server.crt', Bucket, 'server.crt')
                self.s3Client.upload_file('/tmp/server.key', Bucket, 'server.key')
                self.s3Client.upload_file('/tmp/ca.crt', Bucket, 'ca.crt')
            except BaseException as e:
                print(str(e))
                return False
        else:
            print("Download previously generated ssl certificates from S3")
            self.s3Client.download_file(Bucket, 'server.crt', '/tmp/server.crt')
            self.s3Client.download_file(Bucket, 'server.key', '/tmp/server.key')
            self.s3Client.download_file(Bucket, 'ca.crt', '/tmp/ca.crt')

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

    def generateRKEConfig(self, asgInstances, instanceUser, instancePEM, FQDN, rkeCrts):
        rkeConfig = ('ignore_docker_version: true\n'
                '\n'
                'nodes:\n')

        instanceCount = 0
        for instance in asgInstances:
            role = 'etcd,controlplane,worker'
            instanceCount += 1

            rkeConfig += ('  - address: ' + instance['PublicIpAddress'] + '\n'
                            '    user: ' + instanceUser + '\n'
                            '    role: [' + role + ']\n'
                            '    ssh_key: |- \n')
            rkeConfig += self.lambdautils._reindent(instancePEM, 8)
            rkeConfig += '\n'

        #For every node that has the etcd role, these backups are saved to /opt/rke/etcd-snapshots/.
        rkeConfig += ('\n'
        'services:\n'
        '  etcd:\n'
        '    snapshot: true\n'
        '    creation: 6h\n'
        '    retention: 24h\n'
        # '    path: /etcdcluster\n'
        # '    external_urls:\n'
        # '      - https://127.0.0.1:2379\n'
        '\n'
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
        print("Write RKE config yaml to /tmp/config.yaml")