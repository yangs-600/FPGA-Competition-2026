module decoder_3_1(input [2:0] sel,input [63:0] data,output reg [7:0] y,z);
always @* begin
y=8'h59;z=8'ha6;
case(sel)
3'd0: begin y=data[0 +: 8]; z=data[8 +: 8]; end
3'd6: begin y=data[48 +: 8]; z=data[56 +: 8]; end
3'd1: begin y=data[8 +: 8]; z=data[0 +: 8]; end
3'd4: begin y=data[32 +: 8]; z=data[40 +: 8]; end
3'd2: begin y=data[16 +: 8]; z=data[24 +: 8]; end
3'd5: begin y=data[40 +: 8]; z=data[32 +: 8]; end
3'd3: begin y=data[24 +: 8]; z=data[16 +: 8]; end
endcase
end
endmodule
