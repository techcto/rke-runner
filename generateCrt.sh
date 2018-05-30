#Create CA Signing Authority
openssl req \
    -new \
    -newkey rsa:4096 \
    -days 365 \
    -nodes \
    -x509 \
    -subj "/C=US/ST=Florida/L=Orlando/O=spacemade/OU=org unit/CN=spacemade.com" \
    -keyout ca.key \
    -out ca.crt

#Create Certificate
openssl req \
    -new \
    -newkey rsa:4096 \
    -days 365 \
    -nodes \
    -subj "/C=US/ST=Florida/L=Orlando/O=spacemade/OU=org unit/CN=rancher2.spce.io" \
    -keyout server.key \
    -out server.csr

#Sign the certificate from the CA
openssl x509 -req -days 365 -in server.csr -CA ca.crt -CAkey ca.key -set_serial 01 -out server.crt