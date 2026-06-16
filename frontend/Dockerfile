FROM node:20-bullseye

WORKDIR /app

COPY package.json package-lock.json* ./
COPY scripts ./scripts
RUN npm install

COPY . .

EXPOSE 8081 19000 19001 19002

CMD ["npx", "expo", "start", "--lan"]
