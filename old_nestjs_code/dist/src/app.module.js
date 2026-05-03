"use strict";
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.AppModule = void 0;
const common_1 = require("@nestjs/common");
const typeorm_1 = require("@nestjs/typeorm");
const food_entity_1 = require("./food.entity");
const config_1 = require("@nestjs/config");
const seed_service_1 = require("./seed.service");
const food_service_1 = require("./food.service");
const food_controller_1 = require("./food.controller");
let AppModule = class AppModule {
};
exports.AppModule = AppModule;
exports.AppModule = AppModule = __decorate([
    (0, common_1.Module)({
        imports: [
            config_1.ConfigModule.forRoot({
                isGlobal: true,
            }),
            typeorm_1.TypeOrmModule.forRoot({
                type: 'postgres',
                host: process.env.DB_HOST || 'localhost',
                port: parseInt(process.env.DB_PORT || '5432', 10),
                username: process.env.DB_USERNAME || 'postgres',
                password: process.env.DB_PASSWORD || 'txphuc872004',
                database: process.env.DB_NAME || 'food_ai_db',
                entities: [food_entity_1.Food],
                synchronize: true,
            }),
            typeorm_1.TypeOrmModule.forFeature([food_entity_1.Food]),
        ],
        controllers: [food_controller_1.FoodController],
        providers: [food_service_1.FoodService, seed_service_1.SeedService],
    })
], AppModule);
//# sourceMappingURL=app.module.js.map