import { Repository } from 'typeorm';
import { Food } from './food.entity';
import { ConfigService } from '@nestjs/config';
export declare class FoodService {
    private readonly foodRepository;
    private readonly configService;
    private vertexAI;
    private readonly logger;
    private readonly VALID_HARD;
    private readonly VALID_DIET;
    private readonly VALID_SOFT;
    constructor(foodRepository: Repository<Food>, configService: ConfigService);
    searchFood(query: string): Promise<{
        query: string;
        ai_insight: {
            exclude: string[];
            include: string[];
            prefer: string[];
        };
        results: {
            id: any;
            name: any;
            category: any;
            description: any;
            ingredients: any;
            filters: {
                hard: any;
                dietary: any;
                soft: any;
            };
            matchScore: string;
        }[];
    }>;
}
