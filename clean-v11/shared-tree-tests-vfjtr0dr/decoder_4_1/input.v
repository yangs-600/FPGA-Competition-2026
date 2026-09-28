module decoder_4_1(input [3:0] sel,input [127:0] data,output reg [7:0] y,z);
always @* begin
y=8'h59;z=8'ha6;
case(sel)
4'd3: begin y=data[24 +: 8]; z=data[16 +: 8]; end
4'd11: begin y=data[88 +: 8]; z=data[80 +: 8]; end
4'd2: begin y=data[16 +: 8]; z=data[24 +: 8]; end
4'd8: begin y=data[64 +: 8]; z=data[72 +: 8]; end
4'd7: begin y=data[56 +: 8]; z=data[48 +: 8]; end
4'd0: begin y=data[0 +: 8]; z=data[8 +: 8]; end
4'd9: begin y=data[72 +: 8]; z=data[64 +: 8]; end
4'd10: begin y=data[80 +: 8]; z=data[88 +: 8]; end
4'd6: begin y=data[48 +: 8]; z=data[56 +: 8]; end
4'd4: begin y=data[32 +: 8]; z=data[40 +: 8]; end
4'd14: begin y=data[112 +: 8]; z=data[120 +: 8]; end
4'd5: begin y=data[40 +: 8]; z=data[32 +: 8]; end
4'd13: begin y=data[104 +: 8]; z=data[96 +: 8]; end
4'd1: begin y=data[8 +: 8]; z=data[0 +: 8]; end
4'd12: begin y=data[96 +: 8]; z=data[104 +: 8]; end
endcase
end
endmodule
