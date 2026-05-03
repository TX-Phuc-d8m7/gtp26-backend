import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { Food } from './food.entity';
import { ConfigModule } from '@nestjs/config';
import { SeedService } from './seed.service';
import { FoodService } from './food.service';
import { FoodController } from './food.controller';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true, // Cho phép sử dụng biến môi trường ở bất kỳ đâu trong ứng dụng
    }),
    TypeOrmModule.forRoot({
      type: 'postgres',
      host: process.env.DB_HOST || 'localhost',
      port: parseInt(process.env.DB_PORT || '5432', 10),
      username: process.env.DB_USERNAME || 'postgres',
      password: process.env.DB_PASSWORD || 'txphuc872004',
      database: process.env.DB_NAME || 'food_ai_db',
      entities: [Food],
      synchronize: true, // Tự động tạo bảng 'foods' trong DB
    }),
    TypeOrmModule.forFeature([Food]),
  ],
  controllers: [FoodController],
  providers: [FoodService, SeedService],
})
export class AppModule {}