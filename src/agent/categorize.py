"""Nodo del agente para categorizar transacciones."""
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate


class TransactionCategorizer:
    """Categoriza transacciones usando LLM."""
    
    def __init__(self, model: str = "gpt-4o-mini"):
        self.llm = ChatOpenAI(model=model, temperature=0)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """Eres un asistente que categoriza transacciones financieras.
            Categorías disponibles: Comida, Transporte, Servicios, Entretenimiento, 
            Salud, Educación, Compras, Otros.
            
            Responde solo con el nombre de la categoría."""),
            ("human", "Transacción: {description}\nMonto: ${amount}")
        ])
    
    def categorize(self, description: str, amount: float) -> str:
        """Categoriza una transacción."""
        chain = self.prompt | self.llm
        response = chain.invoke({"description": description, "amount": amount})
        return response.content.strip()
