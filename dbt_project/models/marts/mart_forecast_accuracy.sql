-- Mart: Predicted vs actual AQI tracking
-- Evaluates forecast accuracy once actuals are available

with forecasts as (
    select * from {{ source('vayu_raw', 'forecasts') }}
),

stations as (
    select * from {{ source('vayu_raw', 'dim_stations') }}
),

accuracy as (
    select
        f.id as forecast_id,
        f.location_id,
        s.name as station_name,
        s.zone,
        f.forecast_timestamp as forecast_made_at,
        f.target_timestamp,
        f.target_timestamp + interval '5 hours 30 minutes' as target_timestamp_ist,

        -- Predictions
        round(f.predicted_aqi::numeric, 1) as predicted_aqi,
        f.predicted_category,

        -- Actuals (null if not yet available)
        f.actual_aqi,
        f.actual_category,

        -- Error metrics (only when actuals exist)
        case
            when f.actual_aqi is not null then
                round((f.predicted_aqi - f.actual_aqi)::numeric, 1)
            else null
        end as error,

        case
            when f.actual_aqi is not null then
                round(abs(f.predicted_aqi - f.actual_aqi)::numeric, 1)
            else null
        end as absolute_error,

        case
            when f.actual_aqi is not null and f.actual_aqi > 0 then
                round((abs(f.predicted_aqi - f.actual_aqi) / f.actual_aqi * 100)::numeric, 1)
            else null
        end as absolute_percentage_error,

        -- Did we predict the right AQI category?
        case
            when f.actual_category is not null then
                f.predicted_category = f.actual_category
            else null
        end as category_correct,

        -- Lead time: how far ahead was the forecast
        round(extract(epoch from f.target_timestamp - f.forecast_timestamp) / 3600.0) as lead_time_hours,

        f.model_version,
        f.created_at

    from forecasts f
    left join stations s on f.location_id = s.location_id
)

select * from accuracy
order by target_timestamp desc, location_id
