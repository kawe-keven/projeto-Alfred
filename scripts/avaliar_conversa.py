"""Imprime um roteiro fictício e uma ficha para avaliação manual da voz."""

from __future__ import annotations


FALAS = (
    "Que horas são?",
    "Acende a luz da sala.",
    "Apaga a luz do quarto.",
    "Toca uma música tranquila para trabalhar.",
    "Ah, eu queria dizer amanhã, não hoje.",
    "Marca um lembrete para quinta às nove.",
    "Me explica rapidinho o que é inflação.",
    "Quanto dá vinte por cento de cinquenta reais?",
    "A Ana chega depois do almoço. Me lembra de ligar pra ela.",
    "Humm... deixa eu pensar. Qual era mesmo o horário?",
    "Eu falei sala, quer dizer, cozinha.",
    "A reunião é às quinze e quarenta e cinco.",
    "Pode repetir só a última frase?",
    "Valeu, entendi.",
    "Mhm.",
    "Não, peraí, muda para sexta.",
    "Fala mais baixo, por favor.",
    "O endereço é exemplo ponto com barra agenda.",
    "Qual é a diferença entre trinta e cinco e quarenta por cento?",
    "Alfred, pare. Agora continua de onde parou.",
)


def main() -> int:
    print("ROTEIRO MANUAL — use uma fala por vez no Alfred.")
    print("Pontue cada item de 1 a 5. Para cortes e esperas, 1 significa muitos; 5 significa nenhum.")
    print("Esta ficha existe só no console; o programa não acessa o microfone nem grava notas.")
    for indice, fala in enumerate(FALAS, 1):
        print(f"{indice:02d}. Diga: {fala}")
    print()
    print("FICHA DE NOTAS (preencha à mão; não é salva)")
    print("Nº | Cortes | Esperas | Clareza | Naturalidade | Compreensão")
    for indice in range(1, len(FALAS) + 1):
        print(f"{indice:02d} |   _    |    _    |   _    |      _       |      _")
    print("Resumo: cortes indevidos _/5; esperas desnecessárias _/5; clareza _/5; naturalidade _/5; erros de compreensão _/5.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
