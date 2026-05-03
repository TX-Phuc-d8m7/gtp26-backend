import { Injectable, Logger, OnApplicationBootstrap } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository, IsNull } from 'typeorm'; // Thêm IsNull để lọc dữ liệu trống
import { Food } from './food.entity';
import { GoogleAuth } from 'google-auth-library';
import { ConfigService } from '@nestjs/config';
import * as fs from 'fs';
import * as path from 'path';

@Injectable()
export class SeedService implements OnApplicationBootstrap {
  private auth: GoogleAuth;
  private readonly logger = new Logger(SeedService.name);

  constructor(
    @InjectRepository(Food)
    private readonly foodRepository: Repository<Food>,
    private readonly configService: ConfigService,
  ) {
    this.auth = new GoogleAuth({
      scopes: 'https://www.googleapis.com/auth/cloud-platform'
    });
  }

  private delay(ms: number) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async onApplicationBootstrap() {
    this.logger.log('🔍 Đang khởi động tiến trình đồng bộ dữ liệu...');

    try {
      // BƯỚC 1: Nạp dữ liệu thô nếu DB trống
      await this.seedRawData();

      // BƯỚC 2: Cập nhật Vector AI cho những món còn thiếu
      await this.generateEmbeddings();
      
    } catch (error) {
      this.logger.error('❌ Lỗi tiến trình Seed:', error.message);
    }
  }

  private async seedRawData() {
    const totalCount = await this.foodRepository.count();
    
    if (totalCount > 0) {
      this.logger.log('✅ Dữ liệu thô đã tồn tại. Bỏ qua bước nạp file JSON.');
      return;
    }

    this.logger.log('📂 Database trống. Đang nạp dữ liệu từ enriched_foods.json...');
    const filePath = path.resolve(process.cwd(), 'foods_enriched.json');
    
    if (!fs.existsSync(filePath)) {
      this.logger.error(`❌ Không tìm thấy file dữ liệu tại: ${filePath}`);
      return;
    }

    const rawData = fs.readFileSync(filePath, 'utf8');
    const foods = JSON.parse(rawData);

    for (const item of foods) {
      const newFood = this.foodRepository.create({
        name: item.name,
        ingredients: item.ingredients || [],
        description: item.description,
        category: item.category || 'Món khác',
        hard_filters: item.hard_filters || [],
        dietary_filters: item.dietary_filters || [],
        soft_filters: item.soft_filters || [],
        embedding: null, 
      });
      await this.foodRepository.save(newFood);
    }
    this.logger.log(`✅ Đã nạp xong ${foods.length} món ăn vào database.`);
  }

  private async generateEmbeddings() {
    // Chỉ lấy những món chưa có Vector
    const foodsToVectorize = await this.foodRepository.find({
      where: { embedding: IsNull() },
    });

    if (foodsToVectorize.length === 0) {
      this.logger.log('✨ Tất cả món ăn đã có Vector AI. Hệ thống sẵn sàng!');
      return;
    }

    this.logger.log(`🚀 Bắt đầu tạo Vector cho ${foodsToVectorize.length} món...`);

    const client = await this.auth.getClient();
    const projectId = this.configService.get<string>('PROJECT_ID');
    const location = 'us-central1';
    const url = `https://${location}-aiplatform.googleapis.com/v1/projects/${projectId}/locations/${location}/publishers/google/models/text-embedding-004:predict`;

    for (let i = 0; i < foodsToVectorize.length; i++) {
      const food = foodsToVectorize[i];

      try {
        const textToEmbed = `${food.ingredients.join(', ')}. ${food.description}`;
        
        const res = await client.request({
          url,
          method: 'POST',
          data: {
            instances: [{ content: textToEmbed }]
          }
        });

        const vector = (res.data as any).predictions?.[0]?.embeddings?.values;
        if (!vector) throw new Error('Không có vector trả về');

        // Lưu vào DB
        await this.foodRepository.update(food.id, {
          embedding: vector
        });

        this.logger.log(`[${i + 1}/${foodsToVectorize.length}] ✅ Vectorized: ${food.name}`);

        await this.delay(4100); 

      } catch (error) {
        this.logger.error(`❌ Lỗi tại món ${food.name}: ${error.message}`);
        await this.delay(10000);
      }
    }
    this.logger.log('Hoàn tất quá trình embedding cho 500 món ăn.');
  }
}


