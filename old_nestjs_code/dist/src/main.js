"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const core_1 = require("@nestjs/core");
const app_module_1 = require("./app.module");
async function bootstrap() {
    const app = await core_1.NestFactory.create(app_module_1.AppModule);
    app.enableCors({
        origin: 'http://localhost:3005',
        methods: 'GET,HEAD,PUT,PATCH,POST,DELETE',
        preflightContinue: false,
        optionsSuccessStatus: 204,
    });
    const port = parseInt(process.env.APP_PORT || '3000', 10);
    console.log(`Application will run on port: ${port}`);
    await app.listen(process.env.APP_PORT || 3000);
}
bootstrap();
//# sourceMappingURL=main.js.map