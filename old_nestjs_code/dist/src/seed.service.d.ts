import { OnApplicationBootstrap } from '@nestjs/common';
import { Repository } from 'typeorm';
import { Food } from './food.entity';
import { ConfigService } from '@nestjs/config';
export declare class SeedService implements OnApplicationBootstrap {
    private readonly foodRepository;
    private readonly configService;
    private auth;
    private readonly logger;
    constructor(foodRepository: Repository<Food>, configService: ConfigService);
    private delay;
    onApplicationBootstrap(): Promise<void>;
    private seedRawData;
    private generateEmbeddings;
}
