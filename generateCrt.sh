#Create EC2 Key Pair
openssl genrsa -passout pass:x -des3 -out /tmp/private.pem 2048
openssl rsa -passin pass:x -in /tmp/private.pem -outform PEM -pubout -out /tmp/public.pem
openssl rsa -passin pass:x -in /tmp/private.pem -RSAPublicKey_out -out /tmp/rsa.pem

chmod 600 /tmp/private.pem
ssh-keygen -y -P "x" -f /tmp/private.pem > /tmp/rsa.pub
   
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
    -subj "/C=$COUNTRYCODE/ST=$STATE/L=$CITY/O=$ORG/OU=$UNIT/CN=$FQDN" \
    -keyout server.key \
    -out server.csr

#Sign the certificate from the CA
openssl x509 -req -days 365 -in server.csr -CA ca.crt -CAkey ca.key -set_serial 01 -out server.crt

cat ca.crt | base64 -w0
cat server.key | base64 -w0
cat server.crt | base64 -w0