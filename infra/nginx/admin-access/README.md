# Admin access control (optional)

The edge includes every `*.conf` file in this folder inside its `/admin/` locations, the login form
included (`infra/nginx/snippets/app.conf`). There are none by default, so the admin is open to
anyone who can reach the edge, behind Django's own login.

compose.yaml mounts `EDGE_ADMIN_ACCESS_DIR` (default: this folder) read-only at
`/etc/nginx/admin-access`. On a server, point `EDGE_ADMIN_ACCESS_DIR` at a folder of your own
rather than adding files here. Only names ending in `.conf` are included, so a password file can
sit beside them. Reload the edge after a change:
`docker compose exec edge nginx -t && docker compose exec edge nginx -s reload`.

An IP allowlist, `allowlist.conf`:

```nginx
allow 203.0.113.7;
allow 198.51.100.0/24;
deny all;
```

HTTP basic auth in front of Django's login, `basic-auth.conf`, with a `htpasswd` file beside it
(`htpasswd -B -c htpasswd admin`). The edge runs as uid 101, which must be able to read the file:

```nginx
auth_basic "Admin";
auth_basic_user_file /etc/nginx/admin-access/htpasswd;
```

With both, `satisfy any;` lets in an allowed address without a password, and `satisfy all;` (the
default) asks for both.
