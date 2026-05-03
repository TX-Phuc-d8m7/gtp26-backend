import { FoodService } from './food.service';
export declare class FoodController {
    private readonly foodService;
    constructor(foodService: FoodService);
    search(query: string): Promise<{
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
