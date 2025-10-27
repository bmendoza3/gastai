"""Tests para el parser de emails."""
import pytest
from src.parser.email_parser import EmailParser


def test_extract_amount():
    """Test de extracción de montos."""
    parser = EmailParser()
    
    # Test con símbolo de dólar
    assert parser.extract_amount("Total: $123.45") == 123.45
    
    # Test con comas
    assert parser.extract_amount("Monto: $1,234.56") == 1234.56
    
    # Test sin símbolo
    assert parser.extract_amount("Cargo de 99.99") == 99.99


def test_parse_transaction():
    """Test de parseo completo de transacción."""
    parser = EmailParser()
    
    email_body = """
    Transacción realizada:
    Monto: $50.00
    Comercio: Supermercado XYZ
    Fecha: 24/10/2025
    """
    
    # TODO: Implementar test cuando el parser esté completo
    result = parser.parse_transaction(email_body)
    assert result is None  # Por ahora retorna None
