"""
External E-Commerce API Service
Calls tenant's own e-commerce platform for real-time data
"""
import logging
import requests
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


class ExternalAPIService:
    """Service to call tenant's external e-commerce API"""
    
    REQUEST_TIMEOUT = 10  # seconds
    CACHE_TTL = 300  # 5 minutes cache for product data
    
    @staticmethod
    def is_enabled_for_tenant(tenant) -> bool:
        """Check if external API is enabled for tenant"""
        return (
            tenant.external_api_enabled and 
            tenant.external_api_url and 
            tenant.external_api_key
        )
    
    @staticmethod
    def _get_headers(tenant) -> Dict[str, str]:
        """Get headers for API request"""
        return {
            "Authorization": f"Bearer {tenant.external_api_key}",
            "Content-Type": "application/json",
            "User-Agent": "CentralizedLLM-ChatBot/1.0"
        }
    
    @classmethod
    def search_products(cls, tenant, query: str) -> Optional[List[Dict]]:
        """
        Search products on tenant's platform
        
        Expected API:
        GET {external_api_url}/api/products?search={query}
        
        Response format:
        [{"id", "name", "price", "sku", "in_stock", "image_url"}]
        """
        if not cls.is_enabled_for_tenant(tenant):
            return None
        
        try:
            url = f"{tenant.external_api_url}/api/products"
            params = {"search": query}
            headers = cls._get_headers(tenant)
            
            response = requests.get(
                url, 
                params=params, 
                headers=headers, 
                timeout=cls.REQUEST_TIMEOUT
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"[ExternalAPI] Search failed: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"[ExternalAPI] Search error: {e}")
            return None
    
    @classmethod
    def get_product(cls, tenant, product_id: str) -> Optional[Dict]:
        """
        Get product details
        
        Expected API:
        GET {external_api_url}/api/products/{product_id}
        """
        if not cls.is_enabled_for_tenant(tenant):
            return None
        
        try:
            url = f"{tenant.external_api_url}/api/products/{product_id}"
            headers = cls._get_headers(tenant)
            
            response = requests.get(url, headers=headers, timeout=cls.REQUEST_TIMEOUT)
            
            if response.status_code == 200:
                return response.json()
            return None
                
        except Exception as e:
            logger.error(f"[ExternalAPI] Get product error: {e}")
            return None
    
    @classmethod
    def check_stock(cls, tenant, product_id: str) -> Optional[Dict]:
        """
        Check product stock
        
        Expected API:
        GET {external_api_url}/api/products/{product_id}/stock
        """
        if not cls.is_enabled_for_tenant(tenant):
            return None
        
        try:
            url = f"{tenant.external_api_url}/api/products/{product_id}/stock"
            headers = cls._get_headers(tenant)
            
            response = requests.get(url, headers=headers, timeout=cls.REQUEST_TIMEOUT)
            
            if response.status_code == 200:
                return response.json()
            return None
                
        except Exception as e:
            logger.error(f"[ExternalAPI] Stock check error: {e}")
            return None
    
    @classmethod
    def get_order_status(cls, tenant, phone: str = None, email: str = None, order_id: str = None) -> Optional[List[Dict]]:
        """
        Get order status
        
        Expected API:
        GET {external_api_url}/api/orders?phone={phone}
        or
        GET {external_api_url}/api/orders?email={email}
        or
        GET {external_api_url}/api/orders/{order_id}
        """
        if not cls.is_enabled_for_tenant(tenant):
            return None
        
        try:
            headers = cls._get_headers(tenant)
            
            if order_id:
                url = f"{tenant.external_api_url}/api/orders/{order_id}"
            elif phone:
                url = f"{tenant.external_api_url}/api/orders"
                headers["params"] = {"phone": phone}
            elif email:
                url = f"{tenant.external_api_url}/api/orders"
                headers["params"] = {"email": email}
            else:
                return None
            
            response = requests.get(url, headers=headers, timeout=cls.REQUEST_TIMEOUT)
            
            if response.status_code == 200:
                return response.json()
            return None
                
        except Exception as e:
            logger.error(f"[ExternalAPI] Order status error: {e}")
            return None
    
    @classmethod
    def track_shipping(cls, tenant, order_id: str) -> Optional[Dict]:
        """
        Track shipping
        
        Expected API:
        GET {external_api_url}/api/orders/{order_id}/tracking
        """
        if not cls.is_enabled_for_tenant(tenant):
            return None
        
        try:
            url = f"{tenant.external_api_url}/api/orders/{order_id}/tracking"
            headers = cls._get_headers(tenant)
            
            response = requests.get(url, headers=headers, timeout=cls.REQUEST_TIMEOUT)
            
            if response.status_code == 200:
                return response.json()
            return None
                
        except Exception as e:
            logger.error(f"[ExternalAPI] Track shipping error: {e}")
            return None
    
    @classmethod
    def get_price(cls, tenant, product_id: str) -> Optional[Dict]:
        """
        Get current price (with promotions)
        
        Expected API:
        GET {external_api_url}/api/products/{product_id}/price
        """
        if not cls.is_enabled_for_tenant(tenant):
            return None
        
        try:
            url = f"{tenant.external_api_url}/api/products/{product_id}/price"
            headers = cls._get_headers(tenant)
            
            response = requests.get(url, headers=headers, timeout=cls.REQUEST_TIMEOUT)
            
            if response.status_code == 200:
                return response.json()
            return None
                
        except Exception as e:
            logger.error(f"[ExternalAPI] Get price error: {e}")
            return None


def format_stock_response(stock_data: Dict) -> str:
    """Format stock data into user-friendly message"""
    if not stock_data:
        return "I couldn't check the stock at the moment."
    
    available = stock_data.get("available", False)
    qty = stock_data.get("qty", 0)
    
    if available and qty > 0:
        return f"Yes, it's in stock! ({qty} available)"
    elif available and qty == 0:
        return "It's in stock but currently out of stock."
    else:
        return "Sorry, this item is currently out of stock."


def format_order_response(orders: List[Dict]) -> str:
    """Format orders into user-friendly message"""
    if not orders:
        return "I couldn't find any orders with that information."
    
    lines = []
    for order in orders[:3]:  # Show last 3 orders
        order_id = order.get("order_id", "")
        status = order.get("status", "Unknown")
        date = order.get("date", "")
        total = order.get("total", "")
        
        lines.append(f"Order #{order_id} - Status: {status}")
        if date:
            lines.append(f"Date: {date}")
        if total:
            lines.append(f"Total: {total}")
        lines.append("")
    
    return "\n".join(lines) if lines else "No orders found."