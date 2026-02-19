### Installation ###

1) Run: helm upgrade -i ked acme-helm/ked -f ked/preprod.yaml -f secrets://ked/secrets.preprod.enc.yml -n ked --create-namespace

Each secret encrypted with env SOPS key, eg. secrets.preprod.enc.yml is encrypted with preprod key(here are decrypted values just for an example).
