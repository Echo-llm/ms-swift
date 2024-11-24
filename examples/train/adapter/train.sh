CUDA_VISIBLE_DEVICES=0 \
swift sft \
    --model LLM-Research/Meta-Llama-3.1-8B-Instruct \
    --train_type adapter \
    --dataset swift/self-cognition#1000 \
    --num_train_epochs 1 \
    --weight_decay 0.1 \
    --learning_rate 1e-4 \
    --gradient_accumulation_steps 8 \
    --warmup_ratio 0.03 \
    --eval_steps 100 \
    --save_steps 100 \
    --save_total_limit 2 \
    --logging_steps 5 \
    --model_author swift \
    --model_name swift-robot
