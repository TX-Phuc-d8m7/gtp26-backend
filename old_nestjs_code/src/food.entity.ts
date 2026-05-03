import { Entity, Column, PrimaryGeneratedColumn } from 'typeorm';

@Entity('foods')
export class Food {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column()
  name: string;

  @Column({nullable: true})
  category: string;

  @Column('text', { array: true })
  ingredients: string[];

  @Column({ type: 'text' })
  description: string;

  @Column({ type: 'jsonb' })
  hard_filters: string[];

  @Column({ type: 'jsonb', default: [] })
  dietary_filters: string[];

  @Column({ type: 'jsonb' })
  soft_filters: string[];

  @Column({ type: 'halfvec', precision: 768, nullable: true })
  embedding: number[] | null;
}
