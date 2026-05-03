import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import * as dotenv from 'dotenv';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);

  app.enableCors({
    origin: 'http://localhost:3005', // Allow requests from any origin
    methods: 'GET,HEAD,PUT,PATCH,POST,DELETE',
    preflightContinue: false,
    optionsSuccessStatus: 204,
  });

  const port = parseInt(process.env.APP_PORT || '3000', 10);
  console.log(`Application will run on port: ${port}`);

  await app.listen(process.env.APP_PORT || 3000);
}
bootstrap();
