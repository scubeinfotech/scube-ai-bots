"""
Message broker abstraction layer - supports RabbitMQ and Kafka
Used to queue and process WhatsApp messages asynchronously
"""
import logging
import json
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable, Awaitable
import asyncio

logger = logging.getLogger(__name__)


class MessageBroker(ABC):
    """Base class for message broker implementations"""
    
    @abstractmethod
    async def connect(self) -> None:
        """Connect to message broker"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from message broker"""
        pass
    
    @abstractmethod
    async def publish(
        self,
        topic: str,
        message: Dict[str, Any],
        priority: str = "normal"
    ) -> Dict[str, Any]:
        """Publish a message to a topic/queue"""
        pass
    
    @abstractmethod
    async def subscribe(
        self,
        topic: str,
        callback: Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> None:
        """Subscribe to messages from a topic/queue"""
        pass


class RabbitMQBroker(MessageBroker):
    """RabbitMQ message broker implementation"""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 5672,
        username: str = "guest",
        password: str = "guest",
        vhost: str = "/"
    ):
        """Initialize RabbitMQ broker"""
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.vhost = vhost
        self.connection = None
        self.channel = None
        
        # Try to import aio_pika
        try:
            import aio_pika
            self.aio_pika = aio_pika
        except ImportError:
            logger.warning("aio_pika not installed. RabbitMQ features disabled.")
            self.aio_pika = None
    
    async def connect(self) -> None:
        """Connect to RabbitMQ"""
        if not self.aio_pika:
            logger.warning("Cannot connect to RabbitMQ: aio_pika not installed")
            return
        
        try:
            dsn = f"amqp://{self.username}:{self.password}@{self.host}:{self.port}/{self.vhost}"
            self.connection = await self.aio_pika.connect_robust(dsn)
            self.channel = await self.connection.channel()
            logger.info("[RabbitMQ] Connected successfully")
        except Exception as e:
            logger.exception(f"[RabbitMQ] Connection failed: {str(e)}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from RabbitMQ"""
        if self.connection:
            await self.connection.close()
            logger.info("[RabbitMQ] Disconnected")
    
    async def publish(
        self,
        topic: str,
        message: Dict[str, Any],
        priority: str = "normal"
    ) -> Dict[str, Any]:
        """Publish message to RabbitMQ exchange"""
        if not self.channel:
            return {"success": False, "error": "Not connected to RabbitMQ"}
        
        try:
            # Declare exchange and queue
            exchange = await self.channel.declare_exchange(
                f"{topic}_exchange",
                self.aio_pika.ExchangeType.DIRECT,
                durable=True
            )
            queue = await self.channel.declare_queue(topic, durable=True)
            await queue.bind(exchange, topic)
            
            # Publish message
            msg_body = json.dumps(message)
            msg = self.aio_pika.Message(
                body=msg_body.encode(),
                content_type="application/json",
                priority=self._priority_to_int(priority)
            )
            
            await exchange.publish(msg, routing_key=topic)
            logger.info(f"[RabbitMQ] Published to {topic}")
            
            return {"success": True, "topic": topic}
        
        except Exception as e:
            logger.exception(f"[RabbitMQ] Publish failed: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def subscribe(
        self,
        topic: str,
        callback: Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> None:
        """Subscribe to RabbitMQ queue"""
        if not self.channel:
            logger.warning("Cannot subscribe: not connected to RabbitMQ")
            return
        
        try:
            # Declare and bind queue
            queue = await self.channel.declare_queue(topic, durable=True)
            
            logger.info(f"[RabbitMQ] Subscribed to {topic}")
            
            # Process messages
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    try:
                        payload = json.loads(message.body.decode())
                        await callback(payload)
                        await message.ack()
                    except Exception as e:
                        logger.exception(f"[RabbitMQ] Callback error: {str(e)}")
                        await message.nack(requeue=True)
        
        except Exception as e:
            logger.exception(f"[RabbitMQ] Subscribe error: {str(e)}")
    
    def _priority_to_int(self, priority: str) -> int:
        """Convert priority string to integer"""
        priority_map = {
            "low": 0,
            "normal": 5,
            "high": 10
        }
        return priority_map.get(priority, 5)


class KafkaBroker(MessageBroker):
    """Kafka message broker implementation"""
    
    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        group_id: str = "whatsapp-consumer-group"
    ):
        """Initialize Kafka broker"""
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.producer = None
        self.consumer = None
        
        # Try to import aiokafka
        try:
            from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
            self.aiokafka_available = True
            self.AIOKafkaProducer = AIOKafkaProducer
            self.AIOKafkaConsumer = AIOKafkaConsumer
        except ImportError:
            logger.warning("aiokafka not installed. Kafka features disabled.")
            self.aiokafka_available = False
    
    async def connect(self) -> None:
        """Connect to Kafka"""
        if not self.aiokafka_available:
            logger.warning("Cannot connect to Kafka: aiokafka not installed")
            return
        
        try:
            self.producer = self.AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode()
            )
            await self.producer.start()
            logger.info("[Kafka] Connected successfully")
        except Exception as e:
            logger.exception(f"[Kafka] Connection failed: {str(e)}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from Kafka"""
        if self.producer:
            await self.producer.stop()
            logger.info("[Kafka] Disconnected")
    
    async def publish(
        self,
        topic: str,
        message: Dict[str, Any],
        priority: str = "normal"
    ) -> Dict[str, Any]:
        """Publish message to Kafka topic"""
        if not self.producer:
            return {"success": False, "error": "Not connected to Kafka"}
        
        try:
            await self.producer.send_and_wait(topic, message)
            logger.info(f"[Kafka] Published to {topic}")
            return {"success": True, "topic": topic}
        
        except Exception as e:
            logger.exception(f"[Kafka] Publish failed: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def subscribe(
        self,
        topic: str,
        callback: Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> None:
        """Subscribe to Kafka topic"""
        if not self.aiokafka_available:
            logger.warning("Cannot subscribe: aiokafka not installed")
            return
        
        try:
            consumer = self.AIOKafkaConsumer(
                topic,
                bootstrap_servers=self.bootstrap_servers,
                group_id=self.group_id,
                value_deserializer=lambda m: json.loads(m.decode()),
                auto_offset_reset='earliest'
            )
            
            await consumer.start()
            logger.info(f"[Kafka] Subscribed to {topic}")
            
            try:
                async for message in consumer:
                    try:
                        await callback(message.value)
                    except Exception as e:
                        logger.exception(f"[Kafka] Callback error: {str(e)}")
            finally:
                await consumer.stop()
        
        except Exception as e:
            logger.exception(f"[Kafka] Subscribe error: {str(e)}")


class InMemoryBroker(MessageBroker):
    """In-memory message broker for development/testing"""
    
    def __init__(self):
        """Initialize in-memory broker"""
        self.queues: Dict[str, list] = {}
        self.subscribers: Dict[str, list] = []
    
    async def connect(self) -> None:
        """No-op for in-memory broker"""
        logger.info("[InMemory] Broker ready")
    
    async def disconnect(self) -> None:
        """No-op for in-memory broker"""
        logger.info("[InMemory] Broker shutdown")
    
    async def publish(
        self,
        topic: str,
        message: Dict[str, Any],
        priority: str = "normal"
    ) -> Dict[str, Any]:
        """Publish to in-memory queue"""
        if topic not in self.queues:
            self.queues[topic] = []
        
        self.queues[topic].append(message)
        logger.info(f"[InMemory] Published to {topic}")
        
        return {"success": True, "topic": topic, "queue_size": len(self.queues[topic])}
    
    async def subscribe(
        self,
        topic: str,
        callback: Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> None:
        """Subscribe to in-memory queue"""
        logger.info(f"[InMemory] Subscribed to {topic}")
        
        # Process existing messages
        if topic in self.queues:
            for message in self.queues[topic]:
                try:
                    await callback(message)
                except Exception as e:
                    logger.exception(f"[InMemory] Callback error: {str(e)}")


def get_message_broker(
    broker_type: str = "in_memory",
    **kwargs
) -> MessageBroker:
    """
    Factory function to get message broker instance
    
    Args:
        broker_type: Type of broker ("rabbitmq", "kafka", "in_memory")
        **kwargs: Broker-specific initialization parameters
        
    Returns:
        Initialized message broker instance
    """
    if broker_type == "rabbitmq":
        return RabbitMQBroker(**kwargs)
    elif broker_type == "kafka":
        return KafkaBroker(**kwargs)
    elif broker_type == "in_memory":
        return InMemoryBroker()
    else:
        raise ValueError(f"Unknown message broker: {broker_type}")
