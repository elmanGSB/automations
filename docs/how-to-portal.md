# How to Update the jumpersapp.com Portal

The portal at `https://jumpersapp.com` is a static HTML page (`infra/portal/index.html`) served by Caddy on the Paperclip VM at `/var/www/portal/`. It has four cards linking to internal tools. The CI/CD deploy copies the file to `/var/www/portal/` on every push to `main`.

All four links use Cloudflare subdomain URLs — never raw `http://IP:PORT` addresses. GCP's firewall only exposes ports 80, 443, and 3101 publicly; service ports (3200, 3300, etc.) are not reachable directly from the internet.

## Current links

| Card | URL |
|------|-----|
| Interviews DB | `https://teable-admin.jumpersapp.com` |
| Analytics | `https://metabase.jumpersapp.com` |
| Hindsight | `https://hindsight.jumpersapp.com` |
| Paperclip | `https://paperclip.jumpersapp.com` |

All four are behind Cloudflare Access (login required).

---

## Steps

### 1. Edit the portal HTML

Open `infra/portal/index.html` and find the card you want to update. Each card looks like:

```html
<a href="https://SERVICE.jumpersapp.com" class="card" target="_blank">
    <div class="card-icon">🔍</div>
    <div class="card-title">Card Title</div>
    <div class="card-desc">Short description</div>
</a>
```

Change the `href` and update the title/description if needed.

### 2. Commit and push

```bash
git checkout -b fix/portal-update-SERVICE-link
git add infra/portal/index.html
git commit -m "fix(portal): update SERVICE link to new URL"
git push -u origin fix/portal-update-SERVICE-link
gh pr create
```

### 3. Merge

After PR review, merge to `main`. GitHub Actions deploys automatically:

```yaml
- name: Deploy portal to /var/www/portal
  run: |
    ssh ... 'sudo mkdir -p /var/www/portal && sudo cp /home/elmanamador/automations/infra/portal/index.html /var/www/portal/index.html'
```

### 4. Verify

Open `https://jumpersapp.com` in a browser and click the updated card. Confirm it navigates to the new URL (Cloudflare Access login may appear first).

---

## Add a new card

Copy an existing `<a class="card">` block in `infra/portal/index.html` and paste it after the last card inside the `<div class="cards">` container. Use a `*.jumpersapp.com` URL.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Portal still shows old link after deploy | CI/CD step failed, or Caddy is serving a cached file | Check GitHub Actions logs; SSH and run `sudo systemctl status caddy` |
| Click goes to ERR_CONNECTION_TIMED_OUT | Link is a raw IP:PORT (not a Cloudflare subdomain) | Change the `href` to the `*.jumpersapp.com` subdomain |
| 403 or Access denied | The Cloudflare subdomain exists but CF Access isn't configured for it | Check Cloudflare Zero Trust dashboard for the application policy |

---

## Related

- CI/CD reference: [reference-ci-cd.md](reference-ci-cd.md)
- Portal file: `infra/portal/index.html`
- Deploy workflow: `.github/workflows/deploy.yml`
