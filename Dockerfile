# 1. Define a imagem base do Python
FROM python:3.10-slim

# 2. Define a pasta de trabalho dentro do container
WORKDIR /app

# 3. Copia os arquivos de dependências e instala
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copia o resto do código do bot para dentro do container
COPY . .

# 5. Comando para rodar o bot
CMD ["python", "bot.py"]