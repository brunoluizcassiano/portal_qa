import yaml
import os

class MassaValidator:
    def __init__(self, validation_config_path=None):
        # Aqui no futuro podemos carregar regras personalizadas
        self.validation_config_path = validation_config_path

    def validate_fluxo_cartao(self, contexto):
        erros = []

        if not contexto:
            erros.append("Contexto está vazio ou inválido.")
            return erros

        # Valida campos essenciais do cartão (simulação para agora)
        campos_essenciais = ["nome", "idade"]

        for campo in campos_essenciais:
            if campo not in contexto or not contexto[campo]:
                erros.append(f"Campo obrigatório '{campo}' está vazio ou não preenchido.")

        return erros

    def validate_payload(self, payload_padrao, contexto):
        """
        payload_padrao -> payload esperado no fluxo yaml
        contexto -> o que veio realmente da execução
        """
        erros = []

        if not payload_padrao:
            return erros  # Se não tem padrão, não precisa validar

        for campo, valor_esperado in payload_padrao.items():
            if campo not in contexto:
                erros.append(f"Campo '{campo}' não encontrado no contexto retornado.")

            elif contexto[campo] == "" or contexto[campo] is None:
                erros.append(f"Campo '{campo}' está vazio no contexto.")

        return erros
