export declare class Food {
    id: string;
    name: string;
    category: string;
    ingredients: string[];
    description: string;
    hard_filters: string[];
    dietary_filters: string[];
    soft_filters: string[];
    embedding: number[] | null;
}
