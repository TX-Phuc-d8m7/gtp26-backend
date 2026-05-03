import { Injectable, Logger } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { Food } from './food.entity';
import { VertexAI, GenerativeModel } from '@google-cloud/vertexai';
import { ConfigService } from '@nestjs/config';
import { GoogleAuth } from 'google-auth-library';



@Injectable()
export class FoodService {
  private vertexAI: VertexAI;
  private readonly logger = new Logger(FoodService.name);

  private readonly VALID_HARD = [
    "Động vật có vỏ", "Hải sản / Cá", "Đậu phộng / Các loại hạt", "Sữa / Lactose", 
    "Đậu nành", "Lúa mì / Gluten", "Trứng", "Cà chua", "Trái cây có múi", "Mè / Vừng", 
    "Đồ sống / Chín tái", "Tiểu đường", "Cao huyết áp", 
    "Bệnh Thận", "Dạ dày / Đại tràng", "Tim mạch / Mỡ máu", 
    "Viêm họng / Ho / Cảm", "Táo bón"
  ];

  private readonly VALID_DIET = [
    "Thuần chay", "Chay Phật giáo", "Chay trứng sữa", "Hồi giáo (Halal)", 
    "Keto", "Eat Clean", "DASH / Địa Trung Hải"
  ];

  private readonly VALID_SOFT = [
    "Đậm đà", "Thanh đạm", "Chua", "Cay", "Mặn", "Ngọt", "Đắng", "Béo ngậy",
    "Nóng hổi", "Thanh mát / Lạnh", "Món nước", "Món khô / Trộn",
    "Giòn / Giòn rụm", "Dai / Sần sật", "Mềm / Tan trong miệng", "Nước sền sệt",
    "Chiên / Rán", "Nướng", "Hấp / Luộc", "Xào", "Gỏi / Trộn sống",
    "Ăn no", "Ăn vặt", "Mồi nhậu", "Ăn sáng", "Ăn đêm", "Tráng miệng", "Giải rượu", "Giải cảm / Ấm bụng",
    "Đặc sản Đà Nẵng", "Ẩm thực đường phố", "Món Việt truyền thống", "Món Á", "Món Âu"
  ];

  constructor(
    @InjectRepository(Food)
    private readonly foodRepository: Repository<Food>,
    private readonly configService : ConfigService
  ) {
    const projectId = this.configService.get<string>('PROJECT_ID')
    const location = ''

    this.vertexAI = new VertexAI({
      project: projectId,
    });
  }

  async searchFood(query: string) {
    const intentModel = this.vertexAI.getGenerativeModel({ model: "gemini-2.5-flash" });

    const prompt = `
      ### ROLE
      Bạn là một Chuyên gia Thẩm định Dinh dưỡng và Y tế AI. Nhiệm vụ của bạn là bóc tách ý định người dùng thành các Tags hệ thống một cách an toàn tuyệt đối.

      ### SYSTEM TAXONOMY (Chỉ được chọn từ danh sách này)
      - Hard Tags (Rủi ro): [${this.VALID_HARD.join(', ')}]
      - Diet Tags (Chế độ ăn): [${this.VALID_DIET.join(', ')}]
      - Soft Tags (Hương vị/Bối cảnh): [${this.VALID_SOFT.join(', ')}]

      ### THUẬT TOÁN SUY LUẬN (LOGIC STEPS)
      1. **Medical Detection**: Phân tích mọi dấu hiệu về thực thể (Bà bầu, trẻ em, người bệnh) và triệu chứng (ho, đau bụng, sốt...).
      2. **Risk Mapping**: Sử dụng tri thức y khoa để xác định các Chống chỉ định (Contraindications). Ánh xạ chúng vào [exclude].
      3. **Preference Extraction**: Nhận diện món ăn/hương vị người dùng yêu cầu (Gỏi, cay, nóng...).
      4. **Safety Cross-Check (BẮT BUỘC)**: 
        - So sánh [prefer] với [exclude]. 
        - NẾU bất kỳ Tag nào trong [prefer] vi phạm hoặc thuộc nhóm bị cấm bởi [exclude] -> XÓA BỎ Tag đó khỏi [prefer] ngay lập tức.
        - KHÔNG ĐƯỢC "ba phải". An toàn là tuyệt đối, sở thích là thứ yếu.
      5. **Alternative Suggestion**: Nếu sở thích bị xóa, hãy tự chọn một Tag an toàn trong danh sách Soft Tags để thay thế (VD: Thay "Gỏi" bằng "Hấp / Luộc").

      ### NGUYÊN TẮC VÀNG
      - **Sức khỏe > Yêu cầu**: Một bà bầu đòi ăn gỏi sống thì [exclude] là "Đồ sống / Chín tái" và [prefer] KHÔNG ĐƯỢC chứa "Gỏi / Trộn sống".
      - **Phương ngữ**: Tự động chuyển đổi (Bao tử -> Dạ dày, Lạc -> Đậu phộng, Tào tháo đuổi -> Dạ dày/Đại tràng).

      ### OUTPUT FORMAT
      Trả về duy nhất JSON object, không markdown, không giải thích:
      {
        "exclude": ["Tag_Hợp_Lệ"],
        "include": ["Tag_Hợp_Lệ"],
        "prefer": ["Tag_Hợp_Lệ"]
      }

      ### USER QUERY
      "${query}"
    `;

    const intentResult = await intentModel.generateContent(prompt);

    const response = await intentResult.response;
    const responseText = response.candidates?.[0]?.content?.parts?.[0]?.text || '{}';

    let excludeTags: string[] = [];
    let includeTags: string[] = [];
    let preferTags: string[] = [];

    try {
      const text = responseText.replace(/```json|```/g, '').trim();
      const parsedData = JSON.parse(text);
      
      excludeTags = (parsedData.exclude || []).filter(t => this.VALID_HARD.includes(t));
      includeTags = (parsedData.include || []).filter(t => this.VALID_DIET.includes(t));
      preferTags = (parsedData.prefer || []).filter(t => this.VALID_SOFT.includes(t));
    } catch (e) {
      console.error('Lỗi parse JSON từ AI:', e);
    }

    this.logger.log(`🗣️ Input: "${query}"`);
    this.logger.log(`🚫 Exclude: ${excludeTags.join(', ') || 'None'}`);
    this.logger.log(`✅ Include: ${includeTags.join(', ') || 'None'}`);

    this.logger.log(`⭐ Prefer : ${preferTags.join(', ') || 'None'}`);

    // 1.5 Tạo vector embedding bằng Google Cloud REST API
    const auth = new GoogleAuth({
      scopes: 'https://www.googleapis.com/auth/cloud-platform'
    });
    const client = await auth.getClient();
    const projectId = this.configService.get<string>('PROJECT_ID');
    const location = 'us-central1'; // Mặc định Vertex AI dùng us-central1 cho model này

    const url = `https://${location}-aiplatform.googleapis.com/v1/projects/${projectId}/locations/${location}/publishers/google/models/text-embedding-004:predict`;
    
    const res = await client.request({
      url,
      method: 'POST',
      data: {
        instances: [{ content: query }],
        parameters: {
          outputDimensionality: 768
        }
      }
    });

    // Truy cập mảng giá trị số (embeddings)
    const embeddingValues = (res.data as any).predictions?.[0]?.embeddings?.values;
    
    if (!embeddingValues) {
      throw new Error('Không thể tạo vector embedding cho truy vấn này.');
    }

    // Format về dạng chuỗi '[0.1, 0.2...]' để TypeORM đẩy vào PostgreSQL vector
    const queryVector = JSON.stringify(embeddingValues);

    // 2. Xây dựng Query Builder
    const queryBuilder = this.foodRepository
      .createQueryBuilder('food')
      .select([
        'food.id', 
        'food.name', 
        'food.description', 
        'food.category',
        'food.ingredients',   
        'food.hard_filters', 
        'food.dietary_filters',
        'food.soft_filters'
      ])
      // Cosine Distance (<=>)
      .addSelect(`food.embedding <=> '${queryVector}'`, 'distance');

    // 1. HARD FILTERS (Loại trừ dị ứng)
    if (excludeTags.length > 0) {
      queryBuilder.andWhere(`NOT (food.hard_filters ?| ARRAY[:...excludeTags])`, { excludeTags });
    }

    // 2. DIETARY FILTERS (Bắt buộc chế độ ăn)
    if (includeTags.length > 0) {
      queryBuilder.andWhere(`food.dietary_filters ?& ARRAY[:...includeTags]`, { includeTags });
    }

    // 3. THỰC THI & LẤY KẾT QUẢ
    const items = await queryBuilder
      .orderBy('distance', 'ASC') 
      .limit(5)
      .getRawMany();

    // =========================================================================
    // GIAI ĐOẠN 4: FORMAT ĐẦU RA CHO FRONTEND
    // =========================================================================
    return {
      query,
      ai_insight: { 
        exclude: excludeTags, 
        include: includeTags, 
        prefer: preferTags 
      },      
      results: items.map(r => ({
        id: r.food_id,
        name: r.food_name,
        category: r.food_category,
        description: r.food_description,
        ingredients: r.food_ingredients,
        filters: {
           hard: r.food_hard_filters,
           dietary: r.food_dietary_filters,
           soft: r.food_soft_filters
        },
        matchScore: ((1 - parseFloat(r.distance)) * 100).toFixed(1) + '%'
      }))
    };
  }
}