import { Controller, Get, Query, BadRequestException } from '@nestjs/common';
import { FoodService } from './food.service';

@Controller('foods')
export class FoodController {
  constructor(private readonly foodService: FoodService) {}

  @Get('search')
  async search(@Query('q') query: string) {
    if (!query) {
      throw new BadRequestException('Vui lòng nhập câu hỏi tìm kiếm.');
    }
    return await this.foodService.searchFood(query);
  }
}