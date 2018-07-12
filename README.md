#Test locally
#Install: https://github.com/HDE/python-lambda-local
python-lambda-local -l ~/.local/lib/ -e env.json -f run -t 5 rke.py event.json

#RKE: etcd take snapshot
./rke etcd snapshot-save --name etcdsnapshot --config config.yaml

#RKE: etcd restore snapshot
./rke etcd snapshot-restore --name etcdsnapshot --config config.yaml