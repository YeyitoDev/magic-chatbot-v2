# Git Flow - Magic Chatbot v2

## Ramas

| Rama | Propósito |
|------|-----------|
| `main` | Producción - deploy automático a Fly.io |
| `develop` | Desarrollo - integración de features |
| `feature/*` | Features nuevas (ej: `feature/dynamic-pricing`) |
| `fix/*` | Hotfixes (ej: `fix/button-data-invalid`) |

## Flujo de trabajo

```bash
# 1. Crear feature branch
git checkout develop
git pull origin develop
git checkout -b feature/nueva-funcionalidad

# 2. Hacer cambios y commit
git add .
git commit -m "feat: descripción del cambio"

# 3. Push y crear PR
git push origin feature/nueva-funcionalidad
# Crear Pull Request en GitHub de feature/* → develop

# 4. Merge a develop (tras review)
git checkout develop
git merge feature/nueva-funcionalidad
git push origin develop

# 5. Release a main
git checkout main
git merge develop
git tag v2.0.1
git push origin main --tags
# → fly-deploy.yml despliega automáticamente en Fly.io
```

## Convenciones de commit

| Tipo | Ejemplo |
|------|---------|
| `feat:` | `feat: dynamic pricing from database` |
| `fix:` | `fix: button_data_invalid in payment keyboard` |
| `refactor:` | `refactor: extract PricingService from subscription_service` |
| `docs:` | `docs: add Fly.io deployment guide` |
| `chore:` | `chore: update dependencies` |