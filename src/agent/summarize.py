"""Nodo del agente para generar resúmenes financieros."""
from typing import Dict, Any, List
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate


class FinanceSummarizer:
    """Genera resúmenes y análisis financieros."""
    
    def __init__(self, model: str = "gpt-4o-mini"):
        self.llm = ChatOpenAI(model=model, temperature=0.7)
    
    def generate_monthly_summary(self, transactions: List[Dict[str, Any]]) -> str:
        """Genera un resumen mensual de finanzas."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Eres un asistente financiero que genera resúmenes claros 
            y concisos sobre el estado financiero del usuario."""),
            ("human", """Genera un resumen mensual basado en estas transacciones:
            {transactions}
            
            Incluye:
            - Total gastado
            - Categoría con más gastos
            - Comparación con el mes anterior (si aplica)
            - Recomendaciones breves""")
        ])
        
        chain = prompt | self.llm
        response = chain.invoke({"transactions": str(transactions)})
        return response.content
    
    def analyze_spending_pattern(self, transactions: List[Dict[str, Any]]) -> str:
        """Analiza patrones de gasto y genera insights."""
        # TODO: Implementar análisis de patrones
        return "Análisis en desarrollo..."
