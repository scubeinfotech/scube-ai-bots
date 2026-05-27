"""
Document management and RAG service
"""
from sqlalchemy.orm import Session
from app.models import Document
from app.services.vector_knowledge import VectorKnowledgeService
from typing import List, Dict, Any
import uuid


class DocumentService:
    """Service for managing documents and RAG"""
    
    @staticmethod
    def upload_document(
        db: Session,
        tenant_id: str,
        name: str,
        content: str,
        document_type: str = "document",
        category: str = None
    ) -> Dict[str, Any]:
        """Upload a document to knowledge base"""
        document = Document(
            tenant_id=tenant_id,
            name=name,
            content=content,
            document_type=document_type,
            category=category
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        
        return {
            "id": document.id,
            "name": document.name,
            "tenant_id": document.tenant_id,
            "status": "uploaded",
            "created_at": document.created_at.isoformat()
        }
    
    @staticmethod
    def get_tenant_documents(
        db: Session,
        tenant_id: str,
        active_only: bool = True
    ) -> List[Dict[str, Any]]:
        """Get all documents for a tenant"""
        query = db.query(Document).filter(Document.tenant_id == tenant_id)
        
        if active_only:
            query = query.filter(Document.is_active == True)
        
        documents = query.all()
        
        return [
            {
                "id": doc.id,
                "name": doc.name,
                "document_type": doc.document_type,
                "category": doc.category,
                "is_processed": doc.is_processed,
                "is_active": doc.is_active,
                "created_at": doc.created_at.isoformat(),
                "updated_at": doc.updated_at.isoformat()
            }
            for doc in documents
        ]
    
    @staticmethod
    def get_document(db: Session, document_id: str) -> Dict[str, Any]:
        """Get a specific document"""
        doc = db.query(Document).filter(Document.id == document_id).first()
        
        if not doc:
            return {}
        
        return {
            "id": doc.id,
            "name": doc.name,
            "content": doc.content,
            "document_type": doc.document_type,
            "category": doc.category,
            "is_processed": doc.is_processed,
            "is_active": doc.is_active,
            "created_at": doc.created_at.isoformat(),
            "updated_at": doc.updated_at.isoformat()
        }
    
    @staticmethod
    def update_document(
        db: Session,
        document_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Update a document"""
        doc = db.query(Document).filter(Document.id == document_id).first()
        
        if not doc:
            return {}
        
        for key, value in kwargs.items():
            if hasattr(doc, key):
                setattr(doc, key, value)
        
        db.commit()
        db.refresh(doc)
        
        return {
            "id": doc.id,
            "name": doc.name,
            "status": "updated",
            "updated_at": doc.updated_at.isoformat()
        }
    
    @staticmethod
    def mark_as_processed(
        db: Session,
        document_id: str
    ) -> Dict[str, Any]:
        """Mark document as processed/indexed"""
        return DocumentService.update_document(
            db,
            document_id,
            is_processed=True
        )
    
    @staticmethod
    def delete_document(db: Session, document_id: str) -> bool:
        """Soft delete a document"""
        doc = db.query(Document).filter(Document.id == document_id).first()
        
        if not doc:
            return False
        
        doc.is_active = False
        db.commit()
        return True
    
    @staticmethod
    def search_documents(
        db: Session,
        tenant_id: str,
        query: str
    ) -> List[Dict[str, Any]]:
        """Hybrid search: semantic vector hits + keyword fallback."""
        vector_hits = VectorKnowledgeService.search(
            db=db,
            tenant_id=tenant_id,
            query=query,
            top_k=5,
        )

        results: List[Dict[str, Any]] = []
        seen_ids = set()

        for hit in vector_hits:
            doc_id = hit.get("document_id")
            if not doc_id or doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)
            snippet = hit.get("content", "")
            results.append(
                {
                    "id": doc_id,
                    "name": hit.get("source_name") or "Document",
                    "snippet": (snippet[:200] + "...") if len(snippet) > 200 else snippet,
                    "score": hit.get("score", 0),
                    "search_type": "semantic",
                }
            )

        keyword_docs = db.query(Document).filter(
            Document.tenant_id == tenant_id,
            Document.is_active == True,
            (Document.name.ilike(f"%{query}%")) |
            (Document.content.ilike(f"%{query}%"))
        ).limit(10).all()

        for doc in keyword_docs:
            if doc.id in seen_ids:
                continue
            seen_ids.add(doc.id)
            results.append(
                {
                    "id": doc.id,
                    "name": doc.name,
                    "snippet": doc.content[:200] + "..." if len(doc.content) > 200 else doc.content,
                    "score": 0,
                    "search_type": "keyword",
                }
            )

        return results
