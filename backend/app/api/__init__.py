"""
API routers
"""
from . import tenants, chat, health, analytics, admin, whatsapp

ROUTERS = [
    tenants.router,
    chat.router,
    health.router,
    analytics.router,
    admin.router,
    whatsapp.router,
]
