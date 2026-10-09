const express = require('express');
const { Kafka } = require('kafkajs');

const app = express();
const PORT = process.env.PORT || 3001;
const KAFKA_BROKER = process.env.KAFKA_BROKER || 'localhost:9092';
const TOPIC = process.env.KAFKA_TOPIC || 'orders';
const GROUP_ID = process.env.KAFKA_GROUP_ID || 'picker-group';
const INSTANCE_NAME = process.env.INSTANCE_NAME || 'picker-1';

const kafka = new Kafka({
  clientId: INSTANCE_NAME,
  brokers: [KAFKA_BROKER]
});

const consumer = kafka.consumer({ groupId: GROUP_ID });
const processedOrders = [];

app.get('/', (req, res) => {
  res.send(`
    <!DOCTYPE html>
    <html>
    <head><title>Picker Service - ${INSTANCE_NAME}</title></head>
    <body style="font-family: sans-serif; padding: 20px;">
      <h1>Сервис Сборщика: ${INSTANCE_NAME}</h1>
      <p><b>Группа:</b> ${GROUP_ID}</p>
      <h2>Обработанные заказы (всего: ${processedOrders.length}):</h2>
      <ul>
        ${processedOrders.map(o => `<li>
          <b>Order ID:</b> ${o.order_id} | 
          <b>Partition:</b> ${o.partition} | 
          <b>Offset:</b> ${o.offset}
        </li>`).reverse().join('')}
      </ul>
    </body>
    </html>
  `);
});

async function start() {
  let connected = false;
  while (!connected) {
    try {
      await consumer.connect();
      connected = true;
      console.log('Successfully connected to Kafka');
    } catch (err) {
      console.log('Kafka not ready yet, retrying in 3 seconds...');
      await new Promise(resolve => setTimeout(resolve, 3000));
    }
  }

  // Повторяем попытку подписки, пока топик orders не будет создан
  let subscribed = false;
  while (!subscribed) {
    try {
      await consumer.subscribe({ topic: TOPIC, fromBeginning: true });
      subscribed = true;
      console.log(`Successfully subscribed to topic: ${TOPIC}`);
    } catch (err) {
      console.log(`Topic ${TOPIC} not ready yet, retrying in 3 seconds...`);
      await new Promise(resolve => setTimeout(resolve, 3000));
    }
  }

  await consumer.run({
    eachMessage: async ({ topic, partition, message }) => {
      const order = JSON.parse(message.value.toString());
      console.log(`[${INSTANCE_NAME}] Обработка заказа ${order.order_id} из partition ${partition}, offset ${message.offset}`);
      
      await new Promise(resolve => setTimeout(resolve, 500));

      processedOrders.push({
        order_id: order.order_id,
        partition,
        offset: message.offset
      });
    }
  });

  app.listen(PORT, () => {
    console.log(`${INSTANCE_NAME} listening on port ${PORT}`);
  });
}

start();