const express = require('express');
const { Kafka } = require('kafkajs');

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

const PORT = process.env.PORT || 3000;
const KAFKA_BROKER = process.env.KAFKA_BROKER || 'localhost:9092';
const TOPIC = process.env.KAFKA_TOPIC || 'orders';

const kafka = new Kafka({
  clientId: 'user-service',
  brokers: [KAFKA_BROKER]
});

const producer = kafka.producer();

let lastSentLog = null;

app.get('/', (req, res) => {
  res.send(`
    <!DOCTYPE html>
    <html>
    <head><title>User Service - Создание заказа</title></head>
    <body style="font-family: sans-serif; padding: 20px;">
      <h1>Сервис Пользователя</h1>
      <form action="/create-order" method="POST">
        <button type="submit" style="padding: 10px 20px; font-size: 16px;">Создать заказ</button>
      </form>
      <h2>Последний отправленный заказ:</h2>
      <pre>${lastSentLog ? JSON.stringify(lastSentLog, null, 2) : 'Заказов ещё не было'}</pre>
    </body>
    </html>
  `);
});

app.post('/create-order', async (req, res) => {
  const orderId = `order-${Date.now()}`;
  const payload = {
    order_id: orderId,
    items: ['Товар A', 'Товар B'],
    timestamp: new Date().toISOString()
  };

  try {
    const result = await producer.send({
      topic: TOPIC,
      messages: [{ value: JSON.stringify(payload) }]
    });

    lastSentLog = {
      payload,
      partition: result[0].partition,
      offset: result[0].baseOffset
    };

    res.redirect('/');
  } catch (err) {
    res.status(500).send(`Ошибка отправки: ${err.message}`);
  }
});

async function start() {
  let connected = false;
  while (!connected) {
    try {
      await producer.connect();
      connected = true;
      console.log('Successfully connected to Kafka');
    } catch (err) {
      console.log('Kafka not ready yet, retrying in 3 seconds...');
      await new Promise(resolve => setTimeout(resolve, 3000));
    }
  }

  app.listen(PORT, () => {
    console.log(`User service listening on port ${PORT}`);
  });
}

start();