# RUIAN2PG Ansible Deployment

Automated deployment for RUIAN2PG stack on Ubuntu 24.04.

## Components

- **PostgreSQL/PostGIS** - Database with RUIAN data
- **Martin** - Vector tile server
- **Nginx** - Reverse proxy and static file server
- **RUIAN App** - Python application for data import

## Quick Start

```bash
cd ansible

# Edit vault with your database password
ansible-vault create inventory/group_vars/vault.yml
# Set: vault_db_password: "your_secure_password"

# Run full deployment
ansible-playbook playbooks/site.yml --ask-vault-pass

# Or without vault (uses default password - not recommended for production)
ansible-playbook playbooks/site.yml
```

## Directory Structure

```
ansible/
├── ansible.cfg                  # Ansible configuration
├── inventory/
│   ├── hosts.yml               # Server inventory
│   └── group_vars/
│       ├── all.yml             # Common variables
│       └── vault.yml           # Encrypted secrets (ansible-vault)
├── playbooks/
│   ├── site.yml                # Main playbook (full deployment)
│   ├── database.yml            # Database only
│   └── maintenance.yml         # Backup, update, restart
├── roles/
│   ├── common/                 # System packages, locale, timezone
│   ├── docker/                 # Docker CE installation
│   ├── postgresql/             # PostGIS container + migrations
│   ├── martin/                 # Martin tile server
│   ├── nginx/                  # Nginx reverse proxy
│   └── ruian_app/              # RUIAN Python application
└── files/
    ├── web/                    # Static web files
    └── sql/                    # SQL migrations
```

## Playbooks

### Full Deployment

```bash
# Deploy everything
ansible-playbook playbooks/site.yml --ask-vault-pass

# Deploy specific components
ansible-playbook playbooks/site.yml --tags "nginx"
ansible-playbook playbooks/site.yml --tags "postgresql,martin"
```

### Database Only

```bash
ansible-playbook playbooks/database.yml --ask-vault-pass
```

### Maintenance

```bash
# Create database backup
ansible-playbook playbooks/maintenance.yml --tags backup

# Update containers to latest images
ansible-playbook playbooks/maintenance.yml --tags update

# Restart services
ansible-playbook playbooks/maintenance.yml --tags restart

# Show status
ansible-playbook playbooks/maintenance.yml --tags status

# Cleanup unused Docker resources
ansible-playbook playbooks/maintenance.yml --tags cleanup
```

## Post-Deployment

### Import RUIAN Data

After deployment, import RUIAN data manually:

```bash
ssh lukas@46.224.67.103

# Download and import latest data
cd ~/ruian2pg
uv run python scripts/download_ruian.py --latest
uv run python scripts/import_ruian.py --latest

# Or import all municipalities (takes longer)
uv run python scripts/download_ruian.py --municipalities --workers 10
uv run python scripts/import_ruian.py --municipalities
```

### Verify Deployment

```bash
# Health checks
curl http://46.224.67.103/health
curl http://46.224.67.103/tiles/health

# Test tile endpoint
curl -o /tmp/tile.pbf http://46.224.67.103/tiles/obce/10/559/351

# Check database
ssh lukas@46.224.67.103 "docker exec ruian-postgis psql -U ruian -d ruian -c 'SELECT COUNT(*) FROM obce;'"
```

### Access Web UI

Open http://46.224.67.103/ in your browser to view the map.

## Configuration

### Vault Variables

Create encrypted vault file:

```bash
ansible-vault create inventory/group_vars/vault.yml
```

Required variables (use `vault_` prefix by convention):

```yaml
vault_db_password: "your_secure_database_password"
```

Optional variables:

```yaml
vault_ruian_domain: "ruian.example.com"  # For SSL later
```

These are mapped to normal variable names in `all.yml` (e.g., `db_password: "{{ vault_db_password }}"`)

### Edit Vault

```bash
ansible-vault edit inventory/group_vars/vault.yml
```

### Server Configuration

Edit `inventory/hosts.yml` to change server IP or user:

```yaml
all:
  children:
    production:
      hosts:
        ruian-server:
          ansible_host: 46.224.67.103
          ansible_user: lukas
```

## SSL (Future)

SSL via Let's Encrypt can be added later by:

1. Adding a certbot role
2. Updating nginx configuration for HTTPS
3. Setting up auto-renewal

## Troubleshooting

### Check Docker Containers

```bash
ssh lukas@46.224.67.103 "docker ps -a"
```

### View Logs

```bash
# PostgreSQL logs
ssh lukas@46.224.67.103 "docker logs ruian-postgis"

# Martin logs
ssh lukas@46.224.67.103 "docker logs martin"

# Nginx logs
ssh lukas@46.224.67.103 "tail -f /var/log/nginx/ruian_error.log"
```

### Restart Services

```bash
ansible-playbook playbooks/maintenance.yml --tags restart
```

### Reset Database

To completely reset the database (WARNING: destroys all data):

```bash
ssh lukas@46.224.67.103
docker stop ruian-postgis
docker rm ruian-postgis
docker volume rm ruian_pgdata
rm -f ~/.migrations/*.done

# Then redeploy
ansible-playbook playbooks/database.yml --ask-vault-pass
```
