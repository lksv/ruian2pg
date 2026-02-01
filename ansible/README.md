# RUIAN2PG Ansible Deployment

Automated deployment for RUIAN2PG stack on Ubuntu 24.04.

## Components

- **PostgreSQL/PostGIS** - Database with RUIAN data
- **Martin** - Vector tile server
- **Nginx** - Reverse proxy and static file server
- **Certbot** - Let's Encrypt SSL certificate management
- **RUIAN App** - Python application for data import

## Quick Start

```bash
cd ansible

# Create vault password file
echo "your_vault_password" > .vault_pass
chmod 600 .vault_pass

# Create and edit vault with secrets
ansible-vault create inventory/group_vars/all/vault.yml --vault-password-file .vault_pass

# Run full deployment
ansible-playbook playbooks/site.yml --vault-password-file .vault_pass
```

## Directory Structure

```
ansible/
├── ansible.cfg                  # Ansible configuration
├── .vault_pass                  # Vault password (not in git)
├── inventory/
│   ├── hosts.yml               # Server inventory
│   └── group_vars/
│       └── all/
│           ├── main.yml        # Common variables
│           └── vault.yml       # Encrypted secrets
├── playbooks/
│   └── site.yml                # Main playbook (full deployment)
├── roles/
│   ├── common/                 # System packages, locale, timezone
│   ├── docker/                 # Docker CE installation
│   ├── ruian_app/              # RUIAN Python application
│   ├── postgresql/             # PostGIS container + migrations
│   ├── martin/                 # Martin tile server
│   ├── nginx/                  # Nginx reverse proxy
│   └── certbot/                # Let's Encrypt SSL certificates
└── files/
    └── sql/                    # SQL migrations
```

## Playbooks

### Full Deployment

```bash
# Deploy everything
ansible-playbook playbooks/site.yml --vault-password-file .vault_pass

# Deploy specific components
ansible-playbook playbooks/site.yml --vault-password-file .vault_pass --tags "nginx"
ansible-playbook playbooks/site.yml --vault-password-file .vault_pass --tags "postgresql,martin"
```

### Available Tags

- `common` - Base system setup
- `docker` - Docker installation
- `ruian_app` - Application code and dependencies
- `postgresql`, `db` - Database container and migrations
- `martin`, `tiles` - Tile server
- `nginx`, `web` - Web server
- `certbot`, `ssl`, `https` - SSL certificates

## Post-Deployment

### Import RUIAN Data

After deployment, import RUIAN data manually on the server:

```bash
cd ~/ruian2pg

# Download and import latest data
uv run python scripts/download_ruian.py --latest
uv run python scripts/import_ruian.py --latest

# Or import all municipalities (takes longer)
uv run python scripts/download_ruian.py --municipalities --workers 10
uv run python scripts/import_ruian.py --municipalities
```

### Verify Deployment

```bash
# Health checks
curl https://lksvrocks.cz/health
curl https://lksvrocks.cz/tiles/health

# Test tile endpoint
curl -o /tmp/tile.pbf https://lksvrocks.cz/tiles/obce/10/559/351

# Check database
docker exec ruian-postgis psql -U ruian -d ruian -c 'SELECT COUNT(*) FROM obce;'
```

### Access Web UI

Open https://lksvrocks.cz/ in your browser to view the map.

## Configuration

### Vault Variables

Create encrypted vault file:

```bash
ansible-vault create inventory/group_vars/all/vault.yml --vault-password-file .vault_pass
```

Required variables:

```yaml
# Server connection
vault_server_ip: "your.server.ip.address"
vault_server_user: "your_ssh_username"

# Domain and SSL
vault_domain_name: "your-domain.com"
vault_certbot_email: "your-email@example.com"

# Database
vault_db_password: "your_secure_database_password"
```

### Edit Vault

```bash
ansible-vault edit inventory/group_vars/all/vault.yml --vault-password-file .vault_pass
```

### Server Configuration

Server connection details are stored in the vault and referenced in `inventory/hosts.yml`:

```yaml
all:
  children:
    production:
      hosts:
        ruian-server:
          ansible_host: "{{ vault_server_ip }}"
          ansible_user: "{{ vault_server_user }}"
```

## SSL/HTTPS

SSL is automatically configured via Let's Encrypt:

- **First deployment**: Nginx serves HTTP, certbot obtains certificate, nginx is reconfigured for HTTPS
- **Subsequent deployments**: HTTPS is already active
- **Auto-renewal**: Enabled via systemd timer (`certbot.timer`)

### Manual Certificate Commands

```bash
# Check certificate status
sudo certbot certificates

# Test renewal
sudo certbot renew --dry-run

# Force renewal
sudo certbot renew --force-renewal
```

## Troubleshooting

### Check Docker Containers

```bash
docker ps -a
```

### View Logs

```bash
# PostgreSQL logs
docker logs ruian-postgis

# Martin logs
docker logs martin

# Nginx logs
tail -f /var/log/nginx/ruian_error.log

# Certbot logs
cat /var/log/letsencrypt/letsencrypt.log
```

### Restart Services

```bash
# Restart all containers
docker restart ruian-postgis martin

# Reload nginx
sudo systemctl reload nginx
```

### Reset Database

To completely reset the database (WARNING: destroys all data):

```bash
docker stop ruian-postgis
docker rm ruian-postgis
docker volume rm ruian_pgdata
rm -f ~/.migrations/*.done

# Then redeploy
ansible-playbook playbooks/site.yml --vault-password-file .vault_pass --tags postgresql
```
