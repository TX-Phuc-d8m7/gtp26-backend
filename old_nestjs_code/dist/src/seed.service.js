"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
var __metadata = (this && this.__metadata) || function (k, v) {
    if (typeof Reflect === "object" && typeof Reflect.metadata === "function") return Reflect.metadata(k, v);
};
var __param = (this && this.__param) || function (paramIndex, decorator) {
    return function (target, key) { decorator(target, key, paramIndex); }
};
var SeedService_1;
Object.defineProperty(exports, "__esModule", { value: true });
exports.SeedService = void 0;
const common_1 = require("@nestjs/common");
const typeorm_1 = require("@nestjs/typeorm");
const typeorm_2 = require("typeorm");
const food_entity_1 = require("./food.entity");
const google_auth_library_1 = require("google-auth-library");
const config_1 = require("@nestjs/config");
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
let SeedService = SeedService_1 = class SeedService {
    foodRepository;
    configService;
    auth;
    logger = new common_1.Logger(SeedService_1.name);
    constructor(foodRepository, configService) {
        this.foodRepository = foodRepository;
        this.configService = configService;
        this.auth = new google_auth_library_1.GoogleAuth({
            scopes: 'https://www.googleapis.com/auth/cloud-platform'
        });
    }
    delay(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }
    async onApplicationBootstrap() {
        this.logger.log('🔍 Đang khởi động tiến trình đồng bộ dữ liệu...');
        try {
            await this.seedRawData();
            await this.generateEmbeddings();
        }
        catch (error) {
            this.logger.error('❌ Lỗi tiến trình Seed:', error.message);
        }
    }
    async seedRawData() {
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
    async generateEmbeddings() {
        const foodsToVectorize = await this.foodRepository.find({
            where: { embedding: (0, typeorm_2.IsNull)() },
        });
        if (foodsToVectorize.length === 0) {
            this.logger.log('✨ Tất cả món ăn đã có Vector AI. Hệ thống sẵn sàng!');
            return;
        }
        this.logger.log(`🚀 Bắt đầu tạo Vector cho ${foodsToVectorize.length} món...`);
        const client = await this.auth.getClient();
        const projectId = this.configService.get('PROJECT_ID');
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
                const vector = res.data.predictions?.[0]?.embeddings?.values;
                if (!vector)
                    throw new Error('Không có vector trả về');
                await this.foodRepository.update(food.id, {
                    embedding: vector
                });
                this.logger.log(`[${i + 1}/${foodsToVectorize.length}] ✅ Vectorized: ${food.name}`);
                await this.delay(4100);
            }
            catch (error) {
                this.logger.error(`❌ Lỗi tại món ${food.name}: ${error.message}`);
                await this.delay(10000);
            }
        }
        this.logger.log('Hoàn tất quá trình embedding cho 500 món ăn.');
    }
};
exports.SeedService = SeedService;
exports.SeedService = SeedService = SeedService_1 = __decorate([
    (0, common_1.Injectable)(),
    __param(0, (0, typeorm_1.InjectRepository)(food_entity_1.Food)),
    __metadata("design:paramtypes", [typeorm_2.Repository,
        config_1.ConfigService])
], SeedService);
//# sourceMappingURL=seed.service.js.map